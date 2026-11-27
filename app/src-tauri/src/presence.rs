//! Is the user at the Mac? Idle time and screen lock, from CoreGraphics.
//! Neither needs a permission.

/// Seconds since the last keyboard, mouse or trackpad input.
pub fn idle_seconds() -> f64 {
    #[cfg(target_os = "macos")]
    {
        #[link(name = "CoreGraphics", kind = "framework")]
        extern "C" {
            fn CGEventSourceSecondsSinceLastEventType(source_state: i32, event_type: u32) -> f64;
        }
        const COMBINED_SESSION_STATE: i32 = 0;
        const ANY_INPUT_EVENT: u32 = u32::MAX;
        // SAFETY: a plain CoreGraphics query.
        unsafe { CGEventSourceSecondsSinceLastEventType(COMBINED_SESSION_STATE, ANY_INPUT_EVENT) }
    }
    #[cfg(not(target_os = "macos"))]
    {
        0.0
    }
}

/// True while the screen is locked (or the login window is showing).
pub fn screen_locked() -> bool {
    #[cfg(target_os = "macos")]
    {
        use core_foundation::base::{CFType, TCFType};
        use core_foundation::boolean::CFBoolean;
        use core_foundation::dictionary::{CFDictionary, CFDictionaryRef};
        use core_foundation::string::CFString;

        #[link(name = "CoreGraphics", kind = "framework")]
        extern "C" {
            fn CGSessionCopyCurrentDictionary() -> CFDictionaryRef;
        }
        // SAFETY: returns a +1 dictionary or null; wrapped under the create rule.
        let raw = unsafe { CGSessionCopyCurrentDictionary() };
        if raw.is_null() {
            return false;
        }
        let dict: CFDictionary<CFString, CFType> = unsafe { CFDictionary::wrap_under_create_rule(raw) };
        dict.find(CFString::from_static_string("CGSSessionScreenIsLocked"))
            .and_then(|value| value.downcast::<CFBoolean>())
            .map(bool::from)
            .unwrap_or(false)
    }
    #[cfg(not(target_os = "macos"))]
    {
        false
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn presence_queries_answer() {
        let idle = super::idle_seconds();
        assert!(idle >= 0.0);
        println!("idle {idle:.1}s, locked {}", super::screen_locked());
    }
}
