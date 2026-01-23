//! AES-GCM encryption for credential data.
//!
//! This module provides encryption and decryption of credential data
//! using AES-256-GCM for authenticated encryption.

use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Nonce,
};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use rand::Rng;

use crate::error::{AppError, AppResult};

/// Nonce size for AES-GCM (96 bits / 12 bytes).
const NONCE_SIZE: usize = 12;

/// Key size for AES-256 (256 bits / 32 bytes).
const KEY_SIZE: usize = 32;

/// Encryptor for credential data.
#[derive(Clone)]
pub struct Encryptor {
    cipher: Aes256Gcm,
}

impl Encryptor {
    /// Create a new encryptor from a base64-encoded key.
    ///
    /// # Arguments
    ///
    /// * `key_base64` - Base64-encoded 32-byte key
    ///
    /// # Errors
    ///
    /// Returns an error if the key is invalid.
    pub fn from_base64(key_base64: &str) -> AppResult<Self> {
        let key_bytes = BASE64
            .decode(key_base64)
            .map_err(|e| AppError::Encryption(format!("Invalid base64 key: {}", e)))?;

        Self::from_bytes(&key_bytes)
    }

    /// Create a new encryptor from raw key bytes.
    ///
    /// # Arguments
    ///
    /// * `key_bytes` - 32-byte key
    ///
    /// # Errors
    ///
    /// Returns an error if the key length is not 32 bytes.
    pub fn from_bytes(key_bytes: &[u8]) -> AppResult<Self> {
        if key_bytes.len() != KEY_SIZE {
            return Err(AppError::Encryption(format!(
                "Invalid key length: expected {} bytes, got {}",
                KEY_SIZE,
                key_bytes.len()
            )));
        }

        let cipher = Aes256Gcm::new_from_slice(key_bytes)
            .map_err(|e| AppError::Encryption(format!("Failed to create cipher: {}", e)))?;

        Ok(Self { cipher })
    }

    /// Generate a new random 32-byte key.
    pub fn generate_key() -> Vec<u8> {
        let mut key = vec![0u8; KEY_SIZE];
        rand::thread_rng().fill(&mut key[..]);
        key
    }

    /// Generate a new random key and return it as base64.
    pub fn generate_key_base64() -> String {
        BASE64.encode(Self::generate_key())
    }

    /// Encrypt data and return the ciphertext with prepended nonce.
    ///
    /// # Arguments
    ///
    /// * `plaintext` - Data to encrypt
    ///
    /// # Returns
    ///
    /// Encrypted data with 12-byte nonce prepended.
    ///
    /// # Errors
    ///
    /// Returns an error if encryption fails.
    pub fn encrypt(&self, plaintext: &[u8]) -> AppResult<Vec<u8>> {
        // Generate random nonce
        let mut nonce_bytes = [0u8; NONCE_SIZE];
        rand::thread_rng().fill(&mut nonce_bytes);
        let nonce = Nonce::from_slice(&nonce_bytes);

        // Encrypt
        let ciphertext = self
            .cipher
            .encrypt(nonce, plaintext)
            .map_err(|e| AppError::Encryption(format!("Encryption failed: {}", e)))?;

        // Prepend nonce to ciphertext
        let mut result = Vec::with_capacity(NONCE_SIZE + ciphertext.len());
        result.extend_from_slice(&nonce_bytes);
        result.extend_from_slice(&ciphertext);

        Ok(result)
    }

    /// Decrypt data with prepended nonce.
    ///
    /// # Arguments
    ///
    /// * `ciphertext_with_nonce` - Encrypted data with 12-byte nonce prepended
    ///
    /// # Returns
    ///
    /// Decrypted plaintext.
    ///
    /// # Errors
    ///
    /// Returns an error if decryption fails or data is too short.
    pub fn decrypt(&self, ciphertext_with_nonce: &[u8]) -> AppResult<Vec<u8>> {
        if ciphertext_with_nonce.len() < NONCE_SIZE {
            return Err(AppError::Encryption(
                "Ciphertext too short (missing nonce)".to_string(),
            ));
        }

        let (nonce_bytes, ciphertext) = ciphertext_with_nonce.split_at(NONCE_SIZE);
        let nonce = Nonce::from_slice(nonce_bytes);

        let plaintext = self
            .cipher
            .decrypt(nonce, ciphertext)
            .map_err(|e| AppError::Encryption(format!("Decryption failed: {}", e)))?;

        Ok(plaintext)
    }

    /// Encrypt JSON data.
    ///
    /// # Arguments
    ///
    /// * `data` - JSON value to encrypt
    ///
    /// # Returns
    ///
    /// Encrypted bytes with prepended nonce.
    pub fn encrypt_json(&self, data: &serde_json::Value) -> AppResult<Vec<u8>> {
        let json_bytes = serde_json::to_vec(data)?;
        self.encrypt(&json_bytes)
    }

    /// Decrypt to JSON data.
    ///
    /// # Arguments
    ///
    /// * `ciphertext_with_nonce` - Encrypted data with prepended nonce
    ///
    /// # Returns
    ///
    /// Decrypted JSON value.
    pub fn decrypt_json(&self, ciphertext_with_nonce: &[u8]) -> AppResult<serde_json::Value> {
        let plaintext = self.decrypt(ciphertext_with_nonce)?;
        let value = serde_json::from_slice(&plaintext)?;
        Ok(value)
    }
}

/// Encrypt data using a base64-encoded key.
///
/// Convenience function that creates an encryptor and encrypts data.
pub fn encrypt(key_base64: &str, plaintext: &[u8]) -> AppResult<Vec<u8>> {
    let encryptor = Encryptor::from_base64(key_base64)?;
    encryptor.encrypt(plaintext)
}

/// Decrypt data using a base64-encoded key.
///
/// Convenience function that creates an encryptor and decrypts data.
pub fn decrypt(key_base64: &str, ciphertext_with_nonce: &[u8]) -> AppResult<Vec<u8>> {
    let encryptor = Encryptor::from_base64(key_base64)?;
    encryptor.decrypt(ciphertext_with_nonce)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_generate_key() {
        let key = Encryptor::generate_key();
        assert_eq!(key.len(), KEY_SIZE);
    }

    #[test]
    fn test_encrypt_decrypt() {
        let key = Encryptor::generate_key_base64();
        let encryptor = Encryptor::from_base64(&key).unwrap();

        let plaintext = b"Hello, World!";
        let ciphertext = encryptor.encrypt(plaintext).unwrap();

        // Ciphertext should be longer than plaintext (nonce + auth tag)
        assert!(ciphertext.len() > plaintext.len());

        let decrypted = encryptor.decrypt(&ciphertext).unwrap();
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn test_encrypt_decrypt_json() {
        let key = Encryptor::generate_key_base64();
        let encryptor = Encryptor::from_base64(&key).unwrap();

        let data = serde_json::json!({
            "username": "admin",
            "password": "secret123",
            "host": "db.example.com"
        });

        let ciphertext = encryptor.encrypt_json(&data).unwrap();
        let decrypted = encryptor.decrypt_json(&ciphertext).unwrap();

        assert_eq!(decrypted, data);
    }

    #[test]
    fn test_convenience_functions() {
        let key = Encryptor::generate_key_base64();
        let plaintext = b"Test data";

        let ciphertext = encrypt(&key, plaintext).unwrap();
        let decrypted = decrypt(&key, &ciphertext).unwrap();

        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn test_invalid_key_length() {
        let result = Encryptor::from_bytes(&[0u8; 16]); // Wrong size
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_base64_key() {
        let result = Encryptor::from_base64("not-valid-base64!!!");
        assert!(result.is_err());
    }

    #[test]
    fn test_decrypt_tampered_data() {
        let key = Encryptor::generate_key_base64();
        let encryptor = Encryptor::from_base64(&key).unwrap();

        let plaintext = b"Secret data";
        let mut ciphertext = encryptor.encrypt(plaintext).unwrap();

        // Tamper with the ciphertext
        if let Some(byte) = ciphertext.last_mut() {
            *byte ^= 0xFF;
        }

        let result = encryptor.decrypt(&ciphertext);
        assert!(result.is_err());
    }
}
