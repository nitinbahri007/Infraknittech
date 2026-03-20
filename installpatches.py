import os
import subprocess
import sys

FOLDER_PATH = "/root/patches/10.10.10.91_142"

def run_command(cmd):
    try:
        print(f"\n👉 Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True)
        print("✅ Success")
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        return False
    return True

def install_deb_files():
    if not os.path.exists(FOLDER_PATH):
        print("❌ Folder not found:", FOLDER_PATH)
        sys.exit(1)

    deb_files = [f for f in os.listdir(FOLDER_PATH) if f.endswith(".deb")]

    if not deb_files:
        print("❌ No .deb files found")
        sys.exit(1)

    deb_paths = [os.path.join(FOLDER_PATH, f) for f in deb_files]

    print(f"📦 Found {len(deb_files)} packages")

    # Step 1: Install all deb files
    success = run_command(["sudo", "dpkg", "-i"] + deb_paths)

    # Step 2: Fix dependencies if needed
    if not success:
        print("\n🔧 Fixing dependencies...")
        run_command(["sudo", "apt", "--fix-broken", "install", "-y"])

    # Final step (recommended)
    print("\n🔄 Final dependency check...")
    run_command(["sudo", "apt", "install", "-f", "-y"])

    print("\n🎉 Installation process completed!")

if __name__ == "__main__":
    install_deb_files()
