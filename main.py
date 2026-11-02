import os
import sys
import subprocess
import json
import time
import logging
import argparse
import threading
import importlib
from datetime import timedelta

# ==========================================
# 1. نظام التثبيت التلقائي للمتطلبات
# ==========================================
REQUIRED_PACKAGES = {
    "psutil": "psutil",
    "requests": "requests",
    "rich": "rich"
}

def install_dependencies():
    missing_packages = []
    for module in REQUIRED_PACKAGES.keys():
        try:
            importlib.import_module(module)
        except ImportError:
            missing_packages.append(REQUIRED_PACKAGES[module])
    
    if missing_packages:
        print(f"[*] جاري تثبيت المكاتب المفقودة تلقائياً: {', '.join(missing_packages)} ...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"], stdout=subprocess.DEVNULL)
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing_packages])
            print("[+] تم تثبيت جميع المكاتب بنجاح!")
            importlib.invalidate_caches()
        except Exception as e:
            print(f"[!] حدث خطأ أثناء تثبيت المكاتب. يرجى تثبيتها يدوياً.\nالخطأ: {e}")
            sys.exit(1)

install_dependencies()

# ==========================================
# 2. استدعاء المكاتب بعد التأكد من وجودها
# ==========================================
import psutil
import requests
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text

try:
    from xmrig import XMRigManager
except ImportError:
    print("[!] خطأ: لم يتم العثور على ملف/مجلد 'xmrig' الذي يحتوي على 'XMRigManager'.")
    print("تأكد من وجود ملف xmrig.py أو مجلد xmrig في نفس مسار هذه الأداة.")
    sys.exit(1)

# ==========================================
# 3. الإعدادات الأساسية
# ==========================================
CONFIG_FILE = "config.json"
LOG_FILE = "blueminer.log"

logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
pool_stats = {"balance": 0.0, "paid": 0.0}

def check_privileges():
    is_admin = False
    if os.name == 'nt':
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    else:
        is_admin = os.geteuid() == 0

    if not is_admin:
        print("[!] تحذير: أنت لا تقوم بتشغيل الأداة بصلاحيات المسؤول (Administrator/Root).")
        print("[!] قد يؤدي هذا إلى انخفاض سرعة التعدين (Hashrate) لعدم القدرة على تفعيل Huge Pages.")
        time.sleep(2)

# ==========================================
# 4. إدارة الإعدادات عبر الملفات والمدخلات
# ==========================================
def load_config():
    if not os.path.exists(CONFIG_FILE):
        default_config = {
            "wallet": "",
            "pool": "pool.supportxmr.com:443",
            "threads": max(1, os.cpu_count() - 1),
            "tls": True
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(default_config, f, indent=4)
        return default_config
    
    with open(CONFIG_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            print("[!] خطأ: ملف config.json غير صالح (تأكد من صيغة JSON).")
            sys.exit(1)

def update_config_from_args(args, config):
    updated = False
    if args.wallet:
        config["wallet"] = args.wallet
        updated = True
    if args.pool:
        config["pool"] = args.pool
        updated = True
    if args.threads:
        config["threads"] = args.threads
        updated = True
        
    if updated:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
        print(f"[+] تم تحديث الإعدادات وحفظها في {CONFIG_FILE}")
    return config

def validate_config(config):
    if not config.get("wallet") or (not config["wallet"].startswith("4") and not config["wallet"].startswith("8")):
        print("[!] عنوان محفظة Monero غير صالح أو غير موجود.")
        print("استخدم الأمر: python script.py config --wallet YOUR_WALLET")
        sys.exit(1)
    if not config.get("pool"):
        print("[!] عنوان البول (Pool) غير صالح أو غير موجود.")
        sys.exit(1)

# ==========================================
# 5. دوال الإحصائيات والتعدين
# ==========================================
def fetch_pool_stats(wallet):
    while True:
        try:
            res = requests.get(f"https://supportxmr.com/api/miner/{wallet}/stats", timeout=10)
            if res.status_code == 200:
                data = res.json()
                pool_stats["balance"] = float(data.get("amtDue", 0)) / 1e12
                pool_stats["paid"] = float(data.get("amtPaid", 0)) / 1e12
        except requests.exceptions.RequestException:
            pass
        time.sleep(60)

def generate_dashboard(xmrig_manager, config):
    layout = Layout()
    layout.split_column(Layout(name="header", size=3), Layout(name="main"))
    layout["main"].split_row(Layout(name="system"), Layout(name="mining"), Layout(name="pool"))

    header = Panel(Text("BlueMiner - Monero (XMR) RandomX Miner", justify="center", style="bold blue"))
    layout["header"].update(header)

    sys_table = Table(show_header=False, box=None)
    sys_table.add_row("CPU Usage:", f"{psutil.cpu_percent()}%")
    sys_table.add_row("RAM Usage:", f"{psutil.virtual_memory().percent}%")
    layout["system"].update(Panel(sys_table, title="System Stats", border_style="cyan"))

    stats = xmrig_manager.stats
    uptime = str(timedelta(seconds=int(xmrig_manager.get_uptime())))
    mine_table = Table(show_header=False, box=None)
    mine_table.add_row("Status:", "Running" if stats["running"] else "Stopped", style="green" if stats["running"] else "red")
    mine_table.add_row("Uptime:", uptime)
    mine_table.add_row("Hashrate:", f"{stats['hashrate']} H/s")
    mine_table.add_row("Accepted Shares:", str(stats["accepted"]), style="green")
    mine_table.add_row("Rejected Shares:", str(stats["rejected"]), style="red")
    if stats["error"]:
        mine_table.add_row("Last Error:", stats["error"], style="bold red")
    layout["mining"].update(Panel(mine_table, title="Mining Stats", border_style="magenta"))

    pool_table = Table(show_header=False, box=None)
    pool_table.add_row("Pool:", config["pool"])
    pool_table.add_row("Pending Balance:", f"{pool_stats['balance']:.6f} XMR")
    pool_table.add_row("Total Paid:", f"{pool_stats['paid']:.6f} XMR")
    pool_table.add_row("Notice:", "Accepted shares are not confirmed payments.", style="dim")
    layout["pool"].update(Panel(pool_table, title="Pool & Rewards", border_style="yellow"))

    return layout

def start_mining(config):
    validate_config(config)
    manager = XMRigManager()
    
    # التثبيت التلقائي الصامت بدون أسئلة
    if not manager.is_installed():
        print("[*] لم يتم العثور على أداة XMRig. جاري التحميل والتثبيت تلقائياً...")
        try:
            manager.download_and_install()
            print("[+] تم تثبيت XMRig بنجاح.")
        except Exception as e:
            print(f"[!] فشل تحميل وتثبيت XMRig: {e}")
            sys.exit(1)

    logging.info("Starting BlueMiner")
    try:
        manager.start(config["pool"], config["wallet"], config["threads"], config.get("tls", True))
    except Exception as e:
        print(f"[!] حدث خطأ أثناء تشغيل المعدّن: {e}")
        sys.exit(1)

    threading.Thread(target=fetch_pool_stats, args=(config["wallet"],), daemon=True).start()

    try:
        with Live(generate_dashboard(manager, config), refresh_per_second=2) as live:
            while manager.stats["running"]:
                live.update(generate_dashboard(manager, config))
                time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[*] جاري إيقاف التعدين...")
    finally:
        manager.stop()
        logging.info("BlueMiner stopped")

def stop_mining():
    stopped_count = 0
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and 'xmrig' in proc.info['name'].lower():
                proc.kill()
                stopped_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    print(f"[*] تم إيقاف جميع عمليات BlueMiner ({stopped_count} عملية تم إغلاقها).")

def check_status():
    running = False
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] and 'xmrig' in proc.info['name'].lower():
                running = True
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    print(f"BlueMiner Status: {'Running' if running else 'Stopped'}")

# ==========================================
# 6. نقطة بداية البرنامج
# ==========================================
def main():
    check_privileges()

    parser = argparse.ArgumentParser(description="BlueMiner - Auto-Installer & Monero Miner")
    parser.add_argument("command", choices=["start", "stop", "restart", "status", "config"], help="Command to execute")
    
    # خيارات الإعدادات اليدوية
    parser.add_argument("--wallet", "-w", type=str, help="تعديل عنوان محفظة Monero")
    parser.add_argument("--pool", "-p", type=str, help="تعديل عنوان شبكة التعدين (Pool)")
    parser.add_argument("--threads", "-t", type=int, help="تعديل عدد مسارات المعالج (Threads) المستخدمة")
    
    args = parser.parse_args()

    config = load_config()

    # تحديث الإعدادات إذا قام المستخدم بإدخالها عبر الـ arguments
    if args.wallet or args.pool or args.threads:
        config = update_config_from_args(args, config)

    if args.command == "config":
        if not (args.wallet or args.pool or args.threads):
            print("[!] لم تقم بإدخال إعدادات جديدة. استخدم: python script.py config --wallet YOUR_WALLET")
        sys.exit(0)

    elif args.command == "start":
        start_mining(config)
    elif args.command == "stop":
        stop_mining()
    elif args.command == "restart":
        stop_mining()
        time.sleep(2)
        start_mining(config)
    elif args.command == "status":
        check_status()

if __name__ == "__main__":
    main()