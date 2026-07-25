import subprocess
import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description="IPAM & CIDR Test Automation CLI Runner")
    parser.add_argument("-i", "--install", action="store_true", help="Auto-install/update dependencies from requirements.txt before running tests")
    parser.add_argument("-v", "--verbose", action="store_true", default=True, help="Run tests in verbose mode (default: True)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Run tests in quiet mode")
    parser.add_argument("-k", "--filter", type=str, help="Filter tests by name matching pattern (passes to pytest -k)")
    parser.add_argument("--report", action="store_true", help="Generate JUnit XML test report (test-results.xml)")

    args = parser.parse_args()

    # 1. Option: Install dependencies
    if args.install:
        print("==================================================")
        print(">>> Installing dependencies from requirements.txt...")
        print("==================================================")
        res = subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        if res.returncode != 0:
            print("[ERROR] Failed to install/update dependencies.")
            sys.exit(res.returncode)

    # 2. Build pytest execution command
    cmd = [sys.executable, "-m", "pytest", "test_ipam.py"]
    
    if args.quiet:
        cmd.append("-q")
    elif args.verbose:
        cmd.append("-v")

    if args.filter:
        cmd.extend(["-k", args.filter])

    if args.report:
        cmd.append("--junitxml=test-results.xml")
        print(">>> Report option active: generating JUnit XML file...")

    print("==================================================")
    print(f">>> Executing tests command: {' '.join(cmd)}")
    print("==================================================")
    
    # Run pytest command
    res = subprocess.run(cmd)

    print("==================================================")
    if res.returncode == 0:
        print("[SUCCESS] STATUS: ALL TESTS PASSED SUCCESSFULLY!")
    else:
        print("[FAILURE] STATUS: TEST SUITE FAILURE DETECTED!")
    print("==================================================")

    sys.exit(res.returncode)

if __name__ == "__main__":
    main()
