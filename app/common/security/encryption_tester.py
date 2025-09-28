# dev_tools/encryption_tester.py
import os
import sys
from dotenv import load_dotenv

# Add the project root to the Python path
script_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
sys.path.insert(0, project_root)

# Load environment variables (not strictly needed for bcrypt, but good practice)
load_dotenv()

try:
    from app.common.security.passwords import hash_password, verify_password
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Please ensure your Python path is set correctly and dependencies are installed.")
    print("Run this script from the project's root directory.")
    sys.exit(1)


# Function to generate a hash from a plain-text password
def generate_password_hash():
    print("\n--- Generate Password Hash ---")
    password = input("Enter the plain-text password to hash: ")
    try:
        if not password:
            print("Password cannot be empty.")
            return
        password_hash = hash_password(password)
        print("\n--- Result ---")
        print(f"Plain-text password: '{password}'")
        print(f"Generated hash: '{password_hash}'")
        print(f"\n💡 Copy and paste this hash into the 'password_hash' column of your database.")
    except Exception as e:
        print(f"Error: {e}")


# Function to verify a password against a hash
def verify_password_against_hash():
    print("\n--- Verify Password Against Hash ---")
    password = input("Enter the plain-text password to check: ")
    hashed_password = input("Enter the bcrypt hash from the database: ")
    try:
        if verify_password(password, hashed_password):
            print("\n✅ Verification successful! The passwords match.")
        else:
            print("\n❌ Verification failed. The passwords do not match.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("Bcrypt Password Hash Tester for Flask ERP System")
    print("--------------------------------------------------")

    while True:
        print("\nChoose an option:")
        print("1. Generate a Password Hash")
        print("2. Verify a Password against a Hash")
        print("3. Exit")

        choice = input("Enter your choice (1-3): ")

        if choice == '1':
            generate_password_hash()
        elif choice == '2':
            verify_password_against_hash()
        elif choice == '3':
            print("Exiting.")
            break
        else:
            print("Invalid choice. Please enter a number between 1 and 3.")