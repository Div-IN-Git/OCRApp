import os
import io
import sys
import time
import pickle
import config
import tempfile
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
from PyQt5.QtCore import QThread, pyqtSignal
 
from geometry_reconstruct import (
    ocr_line_slices,
    is_blank_page
)

from config import (
    MAX_RETRIES,
    RETRY_DELAY,
    BATCH_SIZE,
    SCOPES
)

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

def authenticate():
    creds = None
    token_path = os.path.join(get_app_dir(), 'token.pkl')
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            cred_path = os.path.join(get_app_dir(), 'credentials.json')
            flow = InstalledAppFlow.from_client_secrets_file(cred_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)
    return build('drive', 'v3', credentials=creds)

def upload_image_as_doc(service, img_path):
    file_metadata = {
        'name': os.path.basename(img_path),
        'mimeType': 'application/vnd.google-apps.document'
    }
    media = MediaFileUpload(img_path, mimetype='image/jpeg', resumable=True)
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id'
    ).execute()
    return file.get('id')

def upload_image_as_doc_with_retry(service, img_path, log_signal=None, error_signal=None):
    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if log_signal:
                log_signal.emit(f"Uploading {os.path.basename(img_path)} (attempt {attempt}/{MAX_RETRIES})")

            file_metadata = {
                'name': os.path.basename(img_path),
                'mimeType': 'application/vnd.google-apps.document'
            }

            media = MediaFileUpload(
                img_path,
                mimetype='image/jpeg',
                resumable=True
            )

            file = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()

            return file.get('id')

        except HttpError as e:
            last_exception = e
            if error_signal:
                error_signal.emit(
                    f"Upload failed ({attempt}/{MAX_RETRIES}) for {os.path.basename(img_path)}: {e}"
                )

        except Exception as e:
            last_exception = e
            if error_signal:
                error_signal.emit(
                    f"Unexpected error ({attempt}/{MAX_RETRIES}) for {os.path.basename(img_path)}: {e}"
                )

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    raise last_exception

def download_text(service, file_id, output_path):
    request = service.files().export_media(fileId=file_id, mimeType='text/plain')
    with io.FileIO(output_path, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

def download_text_with_retry(
    service,
    file_id,
    output_path,
    img_name,
    log_signal=None,
    error_signal=None
):
    last_exception = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if log_signal:
                log_signal.emit(
                    f"Downloading {img_name} (attempt {attempt}/{MAX_RETRIES})"
                )

            request = service.files().export_media(
                fileId=file_id,
                mimeType='text/plain'
            )

            with io.FileIO(output_path, 'wb') as fh:
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()

            return

        except HttpError as e:
            last_exception = e
            if error_signal:
                error_signal.emit(
                    f"Download failed ({attempt}/{MAX_RETRIES}) for {img_name}: {e}"
                )

        except Exception as e:
            last_exception = e
            if error_signal:
                error_signal.emit(
                    f"Unexpected download error ({attempt}/{MAX_RETRIES}) for {img_name}: {e}"
                )

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    raise last_exception

# SINGLE IMAGE OCR
def run_google_ocr_on_image(
    service,
    image_path
    ):
        """
        OCR a single image
        and return extracted text.
        """

        file_id = upload_image_as_doc_with_retry(
            service,
            image_path
        )

        temp_output = tempfile.NamedTemporaryFile(
            suffix=".txt",
            delete=False
        )

        temp_output.close()

        download_text_with_retry(
            service,
            file_id,
            temp_output.name,
            os.path.basename(image_path)
        )

        with open(temp_output.name, 'r', encoding='utf-8') as f:
            text = f.read()

        # cleanup
        try:
            os.remove(temp_output.name)
        except:
            pass

        try:
            service.files().delete(fileId=file_id).execute()
        except:
            pass

        return text

def combine_txts(output_folder):
    combined_path = os.path.join(output_folder, 'combined_output.txt')
    with open(combined_path, 'w', encoding='utf-8') as combined:
        for filename in sorted(os.listdir(output_folder)):
            if filename.endswith('.txt') and filename != 'combined_output.txt':
                full_path = os.path.join(output_folder, filename)
                with open(full_path, 'r', encoding='utf-8') as f:
                    combined.write("\n" + f.read().strip() + "\n")
                os.remove(full_path)

def batch_delete_docs(service, file_ids, log_signal=None, error_signal=None):
    deleted_count = 0
    for fid in file_ids:
        try:
            service.files().delete(fileId=fid).execute()
            deleted_count += 1
        except Exception as e:
            if error_signal:
                error_signal.emit(f"Could not delete a temp doc: {e}")
            else:
                print(f"Could not delete a temp doc: {e}")

    if log_signal:
        log_signal.emit(f"Deleted {deleted_count} temporary Google Docs.")

class OCRWorker(QThread):
    log_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str, object)

    def __init__(self, input_dir, output_dir):
        super().__init__()
        self.input_dir = input_dir
        self.output_dir = output_dir

    def run(self):
        file_ids = []
        file_count = 0
        images = []
        try:
            service = authenticate()
            images = [f for f in os.listdir(self.input_dir) if f.lower().endswith('.jpg')]

            self.log_signal.emit(f"Authenticated with Google Drive: SUCCESS \nFound {len(images)} JPG images.")

            if not images:
                self.error_signal.emit("No JPG images found in input folder.")
                self.cleanup_status = "OCR Aborted"
                self.cleanup_count = 0
                return

            all_batches = []

            for i in range(0, len(images), BATCH_SIZE):
                batch = images[i:i + BATCH_SIZE]
                batch_paths = [os.path.join(self.input_dir, f) for f in batch]
                self.log_signal.emit(f"Uploading batch {i//BATCH_SIZE + 1}: {len(batch)} files")

                batch_ids = {}

                for img_path in batch_paths:
                    img = os.path.basename(img_path)
                    if is_blank_page(img_path):
                        self.log_signal.emit(
                            f"Skipped blank page: {img}"
                        )                    
                        continue
                    
                    try:
                        file_id = upload_image_as_doc_with_retry(
                            service,
                            img_path,
                            log_signal=self.log_signal,
                            error_signal=self.error_signal
                        )

                        batch_ids[img] = file_id
                        file_ids.append(file_id)
                        self.log_signal.emit(f"Uploaded successfully: {img}")

                    except Exception as e:
                        self.error_signal.emit(
                            f"FAILED after {MAX_RETRIES} attempts: {img}\nReason: {e}"
                        )

                all_batches.append(batch_ids)

            self.log_signal.emit("\nAll batches uploaded. Starting download phase...")

            for batch_ids in all_batches:
                for img, file_id in batch_ids.items():
                    try:
                        output_path = os.path.join(
                            self.output_dir,
                            os.path.splitext(img)[0] + '.txt'
                        )

                        download_text_with_retry(
                            service,
                            file_id,
                            output_path,
                            img_name=img,
                            log_signal=self.log_signal,
                            error_signal=self.error_signal
                        )

                        self.log_signal.emit(f"Saved: {output_path}")

                        # GEOMETRY LINE SLICE OCR

                        if config.geometry_enabled:

                            try:

                                original_image_path = os.path.join(
                                    self.input_dir,
                                    img
                                )

                                rebuilt_text = ocr_line_slices(
                                    original_image_path,
                                    lambda p: run_google_ocr_on_image(service, p),
                                    output_dir=self.output_dir
                                )

                                with open(output_path, 'w', encoding='utf-8') as f:
                                    f.write(rebuilt_text)

                                self.log_signal.emit(
                                    f"Geometry line reconstruction complete: {img}"
                                )

                            except Exception as e:

                                self.error_signal.emit(
                                    f"Geometry line reconstruction failed for {img}: {e}"
                                )

                        file_count += 1

                    except Exception as e:
                        self.error_signal.emit(
                            f"FAILED after {MAX_RETRIES} attempts: {img}\nReason: {e}"
                        )

            self.log_signal.emit("\nCombining into one output...")
            combine_txts(self.output_dir)

            self.cleanup_status = "OCR Complete"
            self.cleanup_count = file_count

        except Exception as e:
            self.error_signal.emit(f"Fatal error: {str(e)}")
            self.cleanup_status = "OCR Failed"
            self.cleanup_count = 0

        finally:
            if file_ids:
                self.log_signal.emit("Cleaning up temporary Google Docs...")
                batch_delete_docs(service, file_ids, log_signal=self.log_signal, error_signal=self.error_signal)

            self.log_signal.emit(f"\n==== OCR FINISHED ====\nTotal files processed: {file_count} / {len(images)}\n")
            self.finished_signal.emit(self.cleanup_status, self.cleanup_count)