import os
import time
import stat
import zipfile
import tarfile
import requests
import platform
import threading
import subprocess

class XMRigManager:
    def __init__(self):
        # اكتشاف نظام التشغيل تلقائياً
        self.os_type = platform.system()
        self.exe_name = "xmrig.exe" if self.os_type == "Windows" else "xmrig"
        self.exe_path = os.path.join(os.getcwd(), self.exe_name)
        
        self.process = None
        self.start_time = None
        self.api_port = 3333
        self.stats = {
            "running": False, 
            "hashrate": "0.0", 
            "accepted": 0, 
            "rejected": 0, 
            "error": None
        }

    def is_installed(self):
        return os.path.isfile(self.exe_path)

    def download_and_install(self):
        print(f"Detecting OS: {self.os_type}...")
        api_url = "https://api.github.com/repos/xmrig/xmrig/releases/latest"
        
        try:
            res = requests.get(api_url)
            if res.status_code != 200:
                raise Exception(f"GitHub API Error: {res.status_code} - {res.text}")
                
            response = res.json()
            assets = response.get("assets", [])
            
            if not assets:
                raise Exception(f"No files found in the latest release! API returned: {response.get('message', 'Unknown error')}")

            download_url = None
            asset_name = None

            # بحث ذكي ومرن عن الملفات
            for asset in assets:
                name = asset["name"].lower()

                if self.os_type == "Windows" and name.endswith("windows-x64.zip"):
                    download_url = asset["browser_download_url"]
                    asset_name = asset["name"]
                    break

                elif self.os_type == "Linux" and "linux" in name and "x64.tar.gz" in name:
                    download_url = asset["browser_download_url"]
                    asset_name = asset["name"]
                    break

            if not download_url:
                print("Available files on GitHub:")
                for a in assets:
                    print(f" - {a['name']}")
                raise Exception("Could not find a compatible XMRig release for your OS.")

            print(f"Downloading {asset_name}...")
            archive_path = os.path.join(os.getcwd(), asset_name)
            
            with requests.get(download_url, stream=True) as r:
                r.raise_for_status()
                with open(archive_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            print("Extracting files...")
            if self.os_type == "Windows":
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    for file in zip_ref.namelist():
                        if file.endswith("xmrig.exe"):
                            file_data = zip_ref.read(file)
                            with open(self.exe_path, 'wb') as f:
                                f.write(file_data)
            else:
                with tarfile.open(archive_path, "r:gz") as tar_ref:
                    for member in tar_ref.getmembers():
                        if member.name.endswith("xmrig"):
                            f = tar_ref.extractfile(member)
                            if f:
                                with open(self.exe_path, 'wb') as out_f:
                                    out_f.write(f.read())
                                st = os.stat(self.exe_path)
                                os.chmod(self.exe_path, st.st_mode | stat.S_IEXEC)

            os.remove(archive_path)
            print("Installation complete!")

        except Exception as e:
            print(f"Error downloading XMRig: {e}")
            exit(1)

    def start(self, pool, wallet, threads, tls):
        if not self.is_installed():
            self.stats["error"] = "Executable not found!"
            return

        args = [
            self.exe_path,
            "-o", pool,
            "-u", wallet,
            "-t", str(threads),
            "--http-port", str(self.api_port)
        ]
        
        if self.os_type == "Linux":
            args.append("--background")
            
        if tls:
            args.append("--tls")
            
        args = [arg for arg in args if arg]

        try:
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            self.start_time = time.time()
            self.stats["running"] = True
            self.stats["error"] = None
            
            threading.Thread(target=self._update_stats, daemon=True).start()
            
        except Exception as e:
            self.stats["error"] = str(e)
            self.stats["running"] = False

    def _update_stats(self):
        while self.stats["running"]:
            try:
                res = requests.get(f"http://127.0.0.1:{self.api_port}/1/summary", timeout=2)
                if res.status_code == 200:
                    data = res.json()
                    self.stats["hashrate"] = str(data.get("hashrate", {}).get("total", [0])[0])
                    results = data.get("results", {})
                    self.stats["accepted"] = results.get("shares_good", 0)
                    self.stats["rejected"] = results.get("shares_total", 0) - results.get("shares_good", 0)
            except Exception:
                pass
            time.sleep(2)

    def get_uptime(self):
        if not self.start_time:
            return 0
        return int(time.time() - self.start_time)

    def stop(self):
        self.stats["running"] = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except:
                self.process.kill()
        self.process = None
