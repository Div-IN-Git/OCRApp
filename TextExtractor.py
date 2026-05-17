import os
import sys
import io
import pickle
import time
import subprocess
import traceback
from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLineEdit, QStackedWidget, QSplitter, QVBoxLayout,
    QHBoxLayout, QPushButton, QTextEdit, QLabel, QFileDialog, QMessageBox,
    QToolButton, QMenu, QAction
)
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)  # When running from .exe
    else:
        return os.path.dirname(os.path.abspath(__file__))  # During development

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

MAX_RETRIES = 5
RETRY_DELAY = 3    # seconds

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

            return file.get('id') #success

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

    #All retries failed
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

            return  #SUCCESS

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

    # All retries failed
    raise last_exception


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
        try:
            service = authenticate()
            images = [f for f in os.listdir(self.input_dir) if f.lower().endswith('.jpg')]
            file_ids = []
            self.log_signal.emit(f"Authenticated with Google Drive: SUCCESS \nFound {len(images)} JPG images.")
            

            if not images:
                self.error_signal.emit("No JPG images found in input folder.")
                self.cleanup_status = "OCR Aborted"
                self.cleanup_count = 0
                return

            BATCH_SIZE = 10
            file_count = 0
            all_batches = []

            for i in range(0, len(images), BATCH_SIZE):
                batch = images[i:i + BATCH_SIZE]
                batch_paths = [os.path.join(self.input_dir, f) for f in batch]
                self.log_signal.emit(f"Uploading batch {i//BATCH_SIZE + 1}: {len(batch)} files")

                batch_ids = {}

                for img_path in batch_paths:
                    img = os.path.basename(img_path)
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
                        file_count += 1

                    except Exception as e:
                        self.error_signal.emit(
                            f"FAILED after {MAX_RETRIES} attempts: {img}\nReason: {e}"
                        )

            self.log_signal.emit("\nAll files downloaded. Combining into one output...")
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


class OCRApp(QWidget):
    def __init__(self):
        super().__init__()
        icon_path = os.path.join(get_app_dir(), "appicon.ico")
        self.setWindowIcon(QIcon(icon_path))

        self.setWindowTitle("TEXT EXTRACTOR - Swain Softwares")
        self.resize(1100, 500)
        qr = self.frameGeometry()
        cp = QApplication.desktop().screen().rect().center()
        fcp = cp + QPoint(0, -60)  # Adjusted center point slightly higher
        qr.moveCenter(fcp)
        self.move(qr.topLeft())
        self.browser_active = False
        self.drive_browsers, self.consent_browsers = self.get_available_browsers()
        self.init_ui()

    def get_available_browsers(self):
        persistent = {}
        ephemeral = {}

# ========== GOOGLE CHROME ==========
        chrome_paths = [
            os.path.expandvars(r"%ProgramFiles%/Google/Chrome/Application/chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%/Google/Chrome/Application/chrome.exe"),
            os.path.expandvars(r"%LocalAppData%/Google/Chrome/Application/chrome.exe")
        ]
        for path in chrome_paths:
            if os.path.exists(path):
                def open_chrome_persist(url, p=path):
                    profile_dir = os.path.join(get_app_dir(), "chrome_drive_profile")
                    os.makedirs(profile_dir, exist_ok=True)
                    subprocess.Popen([
                        p,
                        f"--user-data-dir={profile_dir}",
                        "--new-window",
                        url
                    ])
                def open_chrome_incognito(url, p=path):
                    subprocess.Popen([p, "--incognito", "--new-window", url])

                persistent["Google Chrome"] = open_chrome_persist
                ephemeral["Google Chrome"] = open_chrome_incognito
                break
# ========== MICROSOFT EDGE ==========
        edge_path = os.path.expandvars(r"%ProgramFiles(x86)%/Microsoft/Edge/Application/msedge.exe")
        if os.path.exists(edge_path):
            def open_edge_persist(url):
                profile_dir = os.path.join(get_app_dir(), "edge_drive_profile")
                os.makedirs(profile_dir, exist_ok=True)
                subprocess.Popen([
                    edge_path,
                    f"--user-data-dir={profile_dir}",
                    "--new-window",
                    url
                ])
            def open_edge_private(url):
                subprocess.Popen([edge_path, "--inprivate", url])

            persistent["Microsoft Edge"] = open_edge_persist
            ephemeral["Microsoft Edge"] = open_edge_private

# ========== MOZILLA FIREFOX ==========
        firefox_paths = [
            os.path.expandvars(r"%ProgramFiles%/Mozilla Firefox/firefox.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%/Mozilla Firefox/firefox.exe"),
            os.path.expandvars(r"%LocalAppData%/Mozilla Firefox/firefox.exe")
        ]
        for path in firefox_paths:
            if os.path.exists(path):
                def open_firefox_persist(url, p=path):
                    profile_dir = os.path.join(get_app_dir(), "firefox_drive_profile")
                    os.makedirs(profile_dir, exist_ok=True)
                    subprocess.Popen([
                        p,
                        "-no-remote",  # ensures separate instance
                        "-profile", profile_dir,
                        url
                    ])
                def open_firefox_private(url, p=path):
                    subprocess.Popen([p, "--private-window", url])

                persistent["Mozilla Firefox"] = open_firefox_persist
                ephemeral["Mozilla Firefox"] = open_firefox_private
                break

        return persistent, ephemeral

#============== UI ================
    def init_ui(self):
        self.setStyleSheet("QLabel { font-weight: bold; }")

        input_label = QLabel("Select Input Folder:")
        self.input_path = QLineEdit()
        input_browse = QPushButton("Browse")
        input_browse.clicked.connect(self.browse_input)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(1)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(self.input_path)
        input_layout.addWidget(input_browse)

        output_label = QLabel("Select Output Folder:")
        self.output_path = QLineEdit()
        output_browse = QPushButton("Browse")
        output_browse.clicked.connect(self.browse_output)

        output_layout = QHBoxLayout()
        output_layout.setSpacing(1)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.addWidget(self.output_path)
        output_layout.addWidget(output_browse)

        self.ocr_button = QPushButton("START OCR")
        self.ocr_button.setStyleSheet("""
                    QPushButton {
                        background-color: darkred;
                        color: white;
                        font-weight: bold;
                        font-weight: bold;
                        border: 2px solid #4A0A10;
                        border-radius: 5px;
                        padding: 8px 16px;
                    }
                    QPushButton:hover {
                        background-color: #c6122f;
                    }
                    QPushButton:pressed {
                        background-color: #780b1d;
                        padding-left: 10px;
                        padding-top: 10px;
                    }
                    QPushButton:disabled {
                        background-color: #9E9E9E;
                        color: #616161;
                        border: 2px solid #757575;
                    }
                    """)
        self.ocr_button.clicked.connect(self.start_ocr)

        self.drive_button = QPushButton("Open My Drive")
        self.drive_button.clicked.connect(self.open_drive_browser_selector)

        self.cred_button = QPushButton("Import Credentials")
        self.cred_button.clicked.connect(self.import_credentials)


        # DROPDOWN CONSENT SCREEN BUTTON
        self.consent_button = QToolButton()
        self.consent_button.setText("Open Consent Screen")
        self.consent_button.setPopupMode(QToolButton.MenuButtonPopup)
        self.consent_menu = QMenu(self)

        for label, browser in self.consent_browsers.items():
            action = QAction(label, self)
            action.triggered.connect(lambda checked, b=browser, l=label: self.open_browser_with(b, l))
            self.consent_menu.addAction(action)

        if not self.consent_browsers:
            self.consent_menu.addAction(QAction("No browsers found", self))

        self.consent_button.setMenu(self.consent_menu)

        browser_buttons_layout = QHBoxLayout()
        browser_buttons_layout.setSpacing(8)
        browser_buttons_layout.addWidget(self.drive_button)
        browser_buttons_layout.addWidget(self.consent_button)

        self.main_log_label = QLabel("Main Log")
        self.main_log = QTextEdit()
        self.main_log.setReadOnly(True)
        self.main_log.setMinimumHeight(400)

        self.error_log_label = QLabel("Error Log")
        self.error_log = QTextEdit()
        self.error_log.setReadOnly(True)
        self.error_log.setMinimumHeight(400)
        self.error_log.setStyleSheet("color: red;")

        self.log_splitter = QSplitter(Qt.Horizontal)
        self.log_splitter.setSizes([700, 300])
        self.main_stack = QStackedWidget()
        self.main_stack.addWidget(self.main_log)

        log_container = QWidget()
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(2)
        log_layout.addWidget(self.main_log_label)
        log_layout.addWidget(self.main_stack)
        log_container.setLayout(log_layout)

        error_container = QWidget()
        error_layout = QVBoxLayout()
        error_layout.setContentsMargins(0, 0, 0, 0)
        error_layout.setSpacing(2)
        error_layout.addWidget(self.error_log_label)
        error_layout.addWidget(self.error_log)
        error_container.setLayout(error_layout)

        self.log_splitter.addWidget(log_container)
        self.log_splitter.addWidget(error_container)
        self.log_splitter.setStretchFactor(0, 2)
        self.log_splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(input_label)
        layout.addLayout(input_layout)
        layout.addSpacing(5)
        layout.addWidget(output_label)
        layout.addLayout(output_layout)
        layout.addSpacing(10)
        layout.addWidget(self.ocr_button)
        layout.addWidget(self.cred_button)
        layout.addLayout(browser_buttons_layout)
        layout.addSpacing(10)
        layout.addWidget(self.log_splitter)

        self.setLayout(layout)

    def browse_input(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if folder:
            self.input_path.setText(folder)

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_path.setText(folder)

    def start_ocr(self):
        input_dir = self.input_path.text()
        output_dir = self.output_path.text()

        if not os.path.isdir(input_dir):
            QMessageBox.warning(self, "Invalid Input Folder", "Please select a valid input folder.")
            return
        if not os.path.isdir(output_dir):
            QMessageBox.warning(self, "Invalid Output Folder", "Please select a valid output folder.")
            return

        self.ocr_button.setDisabled(True)
        self.append_log("OCR process started...\n")

        self.worker = OCRWorker(input_dir, output_dir)
        self.worker.log_signal.connect(self.append_log)
        self.worker.error_signal.connect(self.append_error)
        self.worker.finished_signal.connect(self.ocr_finished)
        self.worker.start()

    def ocr_finished(self, message, count):
        self.append_log(f"{message} — Total JPGs processed: {count}")
        self.ocr_button.setDisabled(False)
        QMessageBox.information(self, f"OCR Done", f"{message}\n{count} JPG files processed.")

    def append_log(self, message):
        self.main_log.append(message)

    def append_error(self, message):
        self.error_log.append(message)


    def import_credentials(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Google Credentials JSON File", "", "JSON Files (*.json)")
        if file_path:
            try:
                target_path = os.path.join(get_app_dir(), "credentials.json")
                with open(file_path, 'rb') as src, open(target_path, 'wb') as dst:
                    dst.write(src.read())
                QMessageBox.information(self, "Success", "Credentials imported successfully.")
                self.append_log("User credentials.json imported.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to import credentials file:\n{e}")
                self.append_error(f"Import failed: {str(e)}")


    def open_drive_browser_selector(self):
        if self.drive_browsers:
            # Just auto use the first one available
            label, browser = list(self.drive_browsers.items())[0]
            url = "https://drive.google.com/drive/my-drive"
            self.append_log(f"Opening My Drive using: {label}")
            try:
                browser(url)
            except Exception as e:
                self.append_error(f"Failed to open Drive with {label}: {e}")
        else:
            QMessageBox.warning(self, "No Browsers Found", "No compatible browser detected.")

    def open_browser_with(self, browser, label):
        url = "https://console.cloud.google.com/"
        self.append_log(f"Opening consent screen using: {label}")
        try:
            browser(url)
        except Exception as e:
            self.append_error(f"Failed to open browser ({label}): {e}")


if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        window = OCRApp()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        with open("fatal_crash.log", "w") as f:
            f.write(traceback.format_exc())
        raise
