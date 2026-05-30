import os
import sys
import config
import traceback
from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLineEdit, QStackedWidget, QSplitter, QVBoxLayout,
    QHBoxLayout, QPushButton, QTextEdit, QLabel, QFileDialog, QMessageBox,
    QToolButton, QMenu, QAction
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from ocr_engine import OCRWorker, get_app_dir
from config import APP_VERSION
from browser_utils import get_available_browsers

class OCRApp(QWidget):
    def __init__(self):
        super().__init__()
        icon_path = os.path.join(get_app_dir(), "appicon.ico")
        self.setWindowIcon(QIcon(icon_path))

        self.setWindowTitle("TEXT EXTRACTOR - Swain Softwares")
        self.resize(1100, 500)
        qr = self.frameGeometry()
        cp = QApplication.desktop().screen().rect().center()
        fcp = cp + QPoint(0, -60)
        qr.moveCenter(fcp)
        self.move(qr.topLeft())
        self.browser_active = False
        self.drive_browsers, self.consent_browsers = (
            get_available_browsers(get_app_dir)
        )

        self.init_ui()
    
    def toggle_geometry_module(self):
    
        config.geometry_enabled = (
            not config.geometry_enabled
        )

        if config.geometry_enabled:
            return "Geometry Module: ACTIVE"

        return "Geometry Module: INACTIVE"

    # UI SETUP
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

        # Geometry Toggle Button

        self.geometry_toggle = QPushButton("Geometry: OFF")
        self.geometry_toggle.setCheckable(True)

        self.geometry_toggle.setFixedWidth(130)

        self.geometry_toggle.setStyleSheet("""
            QPushButton {
                background-color: rgb(45, 45, 45);
                color: white;
                border: 1px solid rgb(80, 80, 80);
                border-radius: 4px;
                padding: 4px;
            }

            QPushButton:hover {
                background-color: rgb(60, 60, 60);
            }

            QPushButton:checked {
                background-color: rgb(0, 120, 0);
                color: white;
                border: 1px solid rgb(0, 255, 0);
            }

            QPushButton:checked:hover {
                background-color: rgb(0, 150, 0);
            }
        """)

        self.geometry_toggle.clicked.connect(
            self.handle_geometry_toggle
        )

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
        cred_layout = QHBoxLayout()

        cred_layout.addWidget(self.cred_button)
        cred_layout.addWidget(self.geometry_toggle)

        layout.addLayout(cred_layout)
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

    def handle_geometry_toggle(self):

        message = self.toggle_geometry_module()

        if self.geometry_toggle.isChecked():
            self.geometry_toggle.setText("Geometry: ON")
        else:
            self.geometry_toggle.setText("Geometry: OFF")

        self.append_log(message)

    def open_drive_browser_selector(self):
        if self.drive_browsers:
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