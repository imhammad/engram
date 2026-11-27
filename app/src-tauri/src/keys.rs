//! The database encryption key (ADR 0008).
//!
//! On first run a random 256-bit key is generated and stored in the macOS
//! Keychain as a generic password (service "dev.engram.app", account
//! "database-key"). The engine receives it on stdin, never in argv or the
//! environment, and it is never logged.

pub const KEYCHAIN_SERVICE: &str = "dev.engram.app";
pub const KEYCHAIN_ACCOUNT: &str = "database-key";

fn generate() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("could not generate the database key: {e}"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn valid(key: &str) -> bool {
    key.len() == 64 && key.bytes().all(|b| b.is_ascii_hexdigit())
}

/// The key from the Keychain, created and stored on first use.
#[cfg(target_os = "macos")]
pub fn database_key() -> Result<String, String> {
    use security_framework::passwords::{get_generic_password, set_generic_password};

    match get_generic_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) {
        Ok(bytes) => {
            let key = String::from_utf8(bytes).map_err(|_| "the Keychain item for the database key is not text".to_string())?;
            if valid(&key) {
                Ok(key)
            } else {
                Err("the Keychain item for the database key is malformed".into())
            }
        }
        // errSecItemNotFound: first run.
        Err(err) if err.code() == -25300 => {
            let key = generate()?;
            set_generic_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, key.as_bytes())
                .map_err(|e| format!("could not save the database key to the Keychain: {e}"))?;
            println!("[engine] created a new database key in the Keychain");
            Ok(key)
        }
        Err(err) => Err(format!("could not read the database key from the Keychain: {err}")),
    }
}

/// Other platforms have no key store wired up yet, so the encrypted store
/// cannot start there. Windows support (Credential Manager) is future work.
#[cfg(not(target_os = "macos"))]
pub fn database_key() -> Result<String, String> {
    Err("encrypted storage currently needs the macOS Keychain".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_keys_are_256_bit_hex_and_differ() {
        let a = generate().unwrap();
        let b = generate().unwrap();
        assert!(valid(&a) && valid(&b));
        assert_ne!(a, b);
    }

    #[test]
    fn validation_rejects_bad_keys() {
        assert!(!valid("abc"));
        assert!(!valid(&"z".repeat(64)));
    }
}
