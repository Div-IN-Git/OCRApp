import subprocess
import os

def get_available_browsers(get_app_dir):
    persistent = {}
    ephemeral = {}

    # GOOGLE CHROME
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
    # MICROSOFT EDGE
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

    # MSOZILLA FIREFOX
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
                    "-no-remote",
                    "-profile", profile_dir,
                    url
                ])
            def open_firefox_private(url, p=path):
                subprocess.Popen([p, "--private-window", url])

            persistent["Mozilla Firefox"] = open_firefox_persist
            ephemeral["Mozilla Firefox"] = open_firefox_private
            break

    return persistent, ephemeral