#!/usr/bin/env python3
"""
Test script to verify logout functionality in Trends.Earth settings
"""

import os
import sys

# Add the LDMP module to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "LDMP"))


def test_logout_functionality():
    """Test the logout functionality implementation"""

    # Test 1: Check if logout method exists in settings
    try:
        from LDMP.settings import TrendsEarthSettings

        # Check if the class has the logout method
        if hasattr(TrendsEarthSettings, "logout"):
            print("✅ logout() method exists in TrendsEarthSettings class")
        else:
            print("❌ logout() method NOT found in TrendsEarthSettings class")
            return False

        # Check if the class has the update_login_ui_state method
        if hasattr(TrendsEarthSettings, "update_login_ui_state"):
            print(
                "✅ update_login_ui_state() method exists in TrendsEarthSettings class"
            )
        else:
            print(
                "❌ update_login_ui_state() method NOT found in TrendsEarthSettings class"
            )
            return False

        # Check if the class has the showEvent method
        if hasattr(TrendsEarthSettings, "showEvent"):
            print("✅ showEvent() method exists in TrendsEarthSettings class")
        else:
            print("❌ showEvent() method NOT found in TrendsEarthSettings class")
            return False

    except ImportError as e:
        print(f"❌ Could not import TrendsEarthSettings: {e}")
        return False

    # Test 2: Check if API client has logout method
    try:
        from LDMP.api import APIClient

        if hasattr(APIClient, "logout"):
            print("✅ logout() method exists in APIClient class")
        else:
            print("❌ logout() method NOT found in APIClient class")
            return False

    except ImportError as e:
        print(f"❌ Could not import APIClient: {e}")
        return False

    # Test 3: Check UI file for logout button
    ui_file_path = os.path.join(
        os.path.dirname(__file__), "..", "LDMP", "gui", "DlgSettings.ui"
    )
    if os.path.exists(ui_file_path):
        with open(ui_file_path, "r", encoding="utf-8") as f:
            ui_content = f.read()

        if "pushButton_logout" in ui_content:
            print("✅ pushButton_logout found in UI file")
        else:
            print("❌ pushButton_logout NOT found in UI file")
            return False
    else:
        print(f"❌ UI file not found: {ui_file_path}")
        return False

    print("\n🎉 All logout functionality tests passed!")
    return True


def main():
    print("Testing Trends.Earth Logout Functionality")
    print("=" * 45)

    success = test_logout_functionality()

    if success:
        print(
            "\n✅ Logout functionality implementation is complete and ready for testing!"
        )
        print("\nNext steps:")
        print("1. Test the logout functionality in QGIS")
        print("2. Verify that JWT tokens are properly cleared")
        print("3. Confirm that the UI updates correctly after logout")
        print("4. Test the full authentication workflow: login → refresh → logout")
    else:
        print("\n❌ Some tests failed. Please review the implementation.")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
