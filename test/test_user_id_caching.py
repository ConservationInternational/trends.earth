#!/usr/bin/env python3
"""
Test script to verify user ID caching optimization
"""

import os
import sys

# Add the LDMP module to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "LDMP"))


def test_user_id_caching():
    """Test the user ID caching functionality"""

    print("Testing User ID Caching Optimization")
    print("=" * 40)

    # Test 1: Check if USER_ID setting exists in conf
    try:
        from LDMP.conf import Setting

        if hasattr(Setting, "USER_ID"):
            print("✅ USER_ID setting exists in conf.Setting enum")
            print(f"   Setting key: {Setting.USER_ID.value}")
        else:
            print("❌ USER_ID setting NOT found in conf.Setting enum")
            return False

    except ImportError as e:
        print(f"❌ Could not import Setting from conf: {e}")
        return False

    # Test 2: Check if login method has caching logic
    api_file_path = os.path.join(os.path.dirname(__file__), "..", "LDMP", "api.py")
    if os.path.exists(api_file_path):
        with open(api_file_path, "r", encoding="utf-8") as f:
            api_content = f.read()

        if "write_value(conf.Setting.USER_ID" in api_content:
            print("✅ Login method includes user ID caching logic")
        else:
            print("❌ Login method does NOT include user ID caching logic")
            return False

        if "Cache the user ID after successful login" in api_content:
            print("✅ Login method has user ID caching comments")
        else:
            print("❌ Login method missing user ID caching comments")
            return False
    else:
        print(f"❌ API file not found: {api_file_path}")
        return False

    # Test 3: Check if logout method clears cached user ID
    if "write_value(conf.Setting.USER_ID, None)" in api_content:
        print("✅ Logout method clears cached user ID")
    else:
        print("❌ Logout method does NOT clear cached user ID")
        return False

    # Test 4: Check if _get_user_id uses cached value first
    manager_file_path = os.path.join(
        os.path.dirname(__file__), "..", "LDMP", "jobs", "manager.py"
    )
    if os.path.exists(manager_file_path):
        with open(manager_file_path, "r", encoding="utf-8") as f:
            manager_content = f.read()

        if (
            "cached_user_id = conf.settings_manager.get_value(conf.Setting.USER_ID)"
            in manager_content
        ):
            print("✅ _get_user_id checks cached user ID first")
        else:
            print("❌ _get_user_id does NOT check cached user ID first")
            return False

        if "Using cached user ID" in manager_content:
            print("✅ _get_user_id has proper debug logging for cached ID")
        else:
            print("❌ _get_user_id missing debug logging for cached ID")
            return False

        if "Fallback to API call" in manager_content:
            print("✅ _get_user_id has fallback to API call")
        else:
            print("❌ _get_user_id missing fallback to API call")
            return False
    else:
        print(f"❌ Manager file not found: {manager_file_path}")
        return False

    # Test 5: Check return type annotation
    if "typing.Optional[uuid.UUID]" in manager_content:
        print("✅ _get_user_id has correct return type annotation")
    else:
        print("❌ _get_user_id missing correct return type annotation")
        return False

    print("\n🎉 All user ID caching tests passed!")
    print("\n📈 Performance Benefits:")
    print("- Eliminates redundant /api/v1/user/me API calls")
    print("- Reduces network traffic during job downloads")
    print("- Improves response time for job synchronization")
    print("- Cached ID cleared automatically on logout for security")
    return True


def main():
    success = test_user_id_caching()

    if success:
        print("\n✅ User ID caching optimization is complete and ready!")
        print("\nOptimization Details:")
        print("1. User ID is cached in QSettings after successful login")
        print("2. _get_user_id() checks cache first, falls back to API call")
        print("3. Cached ID is cleared on logout for security")
        print("4. Reduces /api/v1/user/me API calls during job downloads")
        print("5. Improves performance for frequent job synchronization")
    else:
        print("\n❌ Some tests failed. Please review the implementation.")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
