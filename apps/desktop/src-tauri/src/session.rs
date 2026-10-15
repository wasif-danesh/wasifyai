// SPDX-License-Identifier: AGPL-3.0-only
//! The window's session with the engine: a short-lived HS256 token signed with the secret the shell
//! generated for this launch and gave the engine in its environment (ADR-0056). The engine checks
//! the same claims as for the web app's tokens (issuer, audience, expiry, subject), with the
//! provider `desktop`.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine as _;
use hmac::{Hmac, KeyInit, Mac};
use serde_json::json;
use sha2::Sha256;
use std::time::{SystemTime, UNIX_EPOCH};

pub const ISSUER: &str = "wasifyai-web";
pub const AUDIENCE: &str = "wasifyai-api";
pub const SUBJECT: &str = "desktop:local";
pub const LIFETIME_SECS: u64 = 15 * 60;

pub struct Token {
    pub value: String,
    pub expires_at: u64,
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

pub fn mint(secret: &str) -> Token {
    mint_at(secret, now_secs())
}

pub fn mint_at(secret: &str, now: u64) -> Token {
    let header = URL_SAFE_NO_PAD.encode(json!({ "alg": "HS256", "typ": "JWT" }).to_string());
    let expires_at = now + LIFETIME_SECS;
    let claims = json!({
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "iat": now,
        "exp": expires_at,
    });
    let payload = URL_SAFE_NO_PAD.encode(claims.to_string());
    let signing_input = format!("{header}.{payload}");
    let mut mac = <Hmac<Sha256> as KeyInit>::new_from_slice(secret.as_bytes())
        .expect("HMAC accepts a key of any length");
    mac.update(signing_input.as_bytes());
    let signature = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    Token {
        value: format!("{signing_input}.{signature}"),
        expires_at,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parts(token: &str) -> (serde_json::Value, serde_json::Value, String) {
        let mut it = token.split('.');
        let h = URL_SAFE_NO_PAD.decode(it.next().unwrap()).unwrap();
        let p = URL_SAFE_NO_PAD.decode(it.next().unwrap()).unwrap();
        (
            serde_json::from_slice(&h).unwrap(),
            serde_json::from_slice(&p).unwrap(),
            it.next().unwrap().to_string(),
        )
    }

    #[test]
    fn the_token_carries_the_claims_the_engine_requires() {
        let t = mint_at("secret-secret-secret-secret-secret-32", 1_000);
        let (header, claims, _) = parts(&t.value);
        assert_eq!(header["alg"], "HS256");
        assert_eq!(claims["iss"], ISSUER);
        assert_eq!(claims["aud"], AUDIENCE);
        assert_eq!(claims["sub"], SUBJECT);
        assert_eq!(claims["iat"], 1_000);
        assert_eq!(claims["exp"], 1_000 + LIFETIME_SECS);
        assert_eq!(t.expires_at, 1_000 + LIFETIME_SECS);
    }

    #[test]
    fn the_signature_depends_on_the_secret() {
        let a = mint_at("secret-secret-secret-secret-secret-32", 5);
        let b = mint_at("other-secret-other-secret-other-secret", 5);
        let (_, _, sa) = parts(&a.value);
        let (_, _, sb) = parts(&b.value);
        assert_ne!(sa, sb);
        // a known HS256 vector: the same inputs always give the same token
        let again = mint_at("secret-secret-secret-secret-secret-32", 5);
        assert_eq!(a.value, again.value);
    }
}
