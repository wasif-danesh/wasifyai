// SPDX-License-Identifier: AGPL-3.0-only
//! The Browser tab of a coding session: a browser of the person's own, beside the chat.
//!
//! It is a second webview inside the main window, placed by the window's page over the tab's area.
//! It is the person's: the coding agent has no way to open a page or to read one. A page reaches the
//! agent only when the person chooses "Add this page to the chat", and then as plain text.
//!
//! What keeps a web page away from the app:
//!
//! - the webview's label is in no capability file, so a page can call none of the shell's commands;
//! - it has a data store of its own, apart from the window's (cookies, storage);
//! - it goes to `http` and `https` addresses only (never `file:`, `tauri:` or another scheme), and
//!   never to a name under `.localhost`, where the app's own page lives on some systems;
//! - a download is refused, and a page cannot open a window.
//!
//! It is created the first time the tab is opened and removed when the session's page is left.

use serde::Serialize;
use tauri::webview::{NewWindowResponse, PageLoadEvent, WebviewBuilder};
use tauri::{AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, Url, WebviewUrl};

pub const LABEL: &str = "code-browser";
/// What the window's page listens to: the address changed, or a page began or ended loading.
pub const CHANGED: &str = "code-browser-changed";
/// The most of a page's text that is given to the chat.
pub const MAX_TEXT: usize = 60_000;
// a store of the browser's own: nothing a page keeps is where the window's own page keeps things
const STORE: [u8; 16] = *b"wasify-codebrowr";

#[derive(Clone, Serialize)]
pub struct Changed {
    pub url: String,
    pub loading: bool,
}

#[derive(Serialize)]
pub struct PageText {
    pub url: String,
    pub title: String,
    pub text: String,
    /// the page had more text than is given
    pub cut: bool,
}

/// A web address the browser may go to: http or https, with a host, of a sane length.
pub fn page_address(given: &str) -> Option<Url> {
    if given.len() > 4000 || given.chars().any(|c| c.is_control()) {
        return None;
    }
    let url = Url::parse(given).ok()?;
    let web = matches!(url.scheme(), "http" | "https");
    let host = url.host_str().unwrap_or_default().to_ascii_lowercase();
    // `tauri.localhost` and `ipc.localhost` are the app's own page and its line to the shell on
    // some systems: a page there would count as the app's. No name under `.localhost` is opened.
    let ours = host.ends_with(".localhost");
    (web && !host.is_empty() && !ours).then_some(url)
}

/// What the person typed into the address box, as an address: an address as it is, a bare host
/// with `https://` in front, and anything else as a search.
pub fn address_from_typed(typed: &str) -> Option<Url> {
    let typed = typed.trim();
    if typed.is_empty() || typed.len() > 2000 {
        return None;
    }
    if typed.contains("://") {
        return page_address(typed);
    }
    let one_word = !typed.chars().any(char::is_whitespace);
    let local = typed.starts_with("localhost") || typed.starts_with("127.0.0.1");
    if one_word && local {
        return page_address(&format!("http://{typed}"));
    }
    if one_word && typed.contains('.') {
        return page_address(&format!("https://{typed}"));
    }
    let mut search = Url::parse("https://duckduckgo.com/").ok()?;
    search.query_pairs_mut().append_pair("q", typed);
    Some(search)
}

fn area(
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Option<(LogicalPosition<f64>, LogicalSize<f64>)> {
    let sane = [x, y, width, height].iter().all(|v| v.is_finite())
        && x >= 0.0
        && y >= 0.0
        && (1.0..=20_000.0).contains(&width)
        && (1.0..=20_000.0).contains(&height);
    sane.then(|| (LogicalPosition::new(x, y), LogicalSize::new(width, height)))
}

/// Show the browser over an area of the window, at an address. The first call makes it; later
/// calls move it there and, with an address, go to it.
#[tauri::command]
pub async fn browser_show(
    app: AppHandle,
    url: Option<String>,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    let (position, size) = area(x, y, width, height).ok_or("that is not an area of the window")?;
    let address = match url.as_deref() {
        Some(typed) => Some(address_from_typed(typed).ok_or("that is not a web address")?),
        None => None,
    };
    if let Some(view) = app.get_webview(LABEL) {
        view.set_position(position).map_err(|e| e.to_string())?;
        view.set_size(size).map_err(|e| e.to_string())?;
        view.show().map_err(|e| e.to_string())?;
        if let Some(address) = address {
            view.navigate(address).map_err(|e| e.to_string())?;
        }
        return Ok(());
    }
    let window = app.get_window("main").ok_or("the window is not there")?;
    let first = address.unwrap_or_else(|| Url::parse("about:blank").expect("a fixed address"));
    let told = app.clone();
    let builder = WebviewBuilder::new(LABEL, WebviewUrl::External(first))
        .data_store_identifier(STORE)
        .on_navigation(|to| to.as_str() == "about:blank" || page_address(to.as_str()).is_some())
        .on_new_window(|_, _| NewWindowResponse::Deny)
        .on_download(|_, _| false)
        .on_page_load(move |view, payload| {
            let _ = told.emit_to(
                "main",
                CHANGED,
                Changed {
                    url: view.url().map(|u| u.to_string()).unwrap_or_default(),
                    loading: matches!(payload.event(), PageLoadEvent::Started),
                },
            );
        });
    window
        .add_child(builder, position, size)
        .map(|_| ())
        .map_err(|e| format!("the browser could not be opened: {e}"))
}

/// Take the browser off the screen (another tab is shown, or a dialog is open over it). The page
/// stays as it is.
#[tauri::command]
pub fn browser_hide(app: AppHandle) {
    if let Some(view) = app.get_webview(LABEL) {
        let _ = view.hide();
    }
}

/// Remove the browser: the session's page was left.
#[tauri::command]
pub fn browser_close(app: AppHandle) {
    if let Some(view) = app.get_webview(LABEL) {
        let _ = view.close();
    }
}

/// Back, forward, load again, or stop loading.
#[tauri::command]
pub fn browser_go(app: AppHandle, to: String) -> Result<(), String> {
    let view = app.get_webview(LABEL).ok_or("the browser is not open")?;
    let script = match to.as_str() {
        "back" => "history.back()",
        "forward" => "history.forward()",
        "stop" => "window.stop()",
        "reload" => return view.reload().map_err(|e| e.to_string()),
        _ => return Err("there is no such step".into()),
    };
    view.eval(script).map_err(|e| e.to_string())
}

// The page's own words, as the person sees them: its title and its visible text. Run in the page
// only when the person asks for it. It reads; it changes nothing in the page.
const READ_PAGE: &str = "(() => { try { \
    const text = (document.body && document.body.innerText) || ''; \
    return JSON.stringify({ title: document.title || '', text: text.slice(0, 200000) }); \
  } catch (e) { return JSON.stringify({ title: '', text: '' }); } })()";

/// Cut a page's text to what the chat is given, at a character's edge, with runs of empty lines
/// made one.
pub fn tidy_text(text: &str) -> (String, bool) {
    let mut out = String::with_capacity(text.len().min(MAX_TEXT));
    let mut empty = 0;
    for line in text.lines() {
        let line = line.trim_end();
        if line.trim().is_empty() {
            empty += 1;
            if empty > 1 {
                continue;
            }
        } else {
            empty = 0;
        }
        out.push_str(line);
        out.push('\n');
    }
    let out = out.trim().to_string();
    if out.chars().count() <= MAX_TEXT {
        return (out, false);
    }
    (out.chars().take(MAX_TEXT).collect(), true)
}

/// What the script gave back, which the system hands over as JSON once or twice wrapped.
pub fn read_answer(raw: &str) -> Option<(String, String)> {
    let mut value: serde_json::Value = serde_json::from_str(raw).ok()?;
    if let serde_json::Value::String(inner) = &value {
        value = serde_json::from_str(inner).ok()?;
    }
    let title = value.get("title")?.as_str()?.to_string();
    let text = value.get("text")?.as_str()?.to_string();
    Some((title, text))
}

/// The page that is shown, as plain text: for "Add this page to the chat".
#[tauri::command]
pub async fn browser_text(app: AppHandle) -> Result<PageText, String> {
    let view = app.get_webview(LABEL).ok_or("the browser is not open")?;
    let url = view
        .url()
        .map(|u| u.to_string())
        .map_err(|e| e.to_string())?;
    if page_address(&url).is_none() {
        return Err("there is no page to add yet".into());
    }
    let (tx, rx) = tokio::sync::oneshot::channel::<String>();
    let tx = std::sync::Mutex::new(Some(tx));
    view.eval_with_callback(READ_PAGE, move |answer| {
        if let Some(tx) = tx.lock().ok().and_then(|mut t| t.take()) {
            let _ = tx.send(answer);
        }
    })
    .map_err(|e| e.to_string())?;
    let raw = tokio::time::timeout(std::time::Duration::from_secs(10), rx)
        .await
        .map_err(|_| "the page did not answer".to_string())?
        .map_err(|_| "the page did not answer".to_string())?;
    let (title, text) = read_answer(&raw).ok_or("the page's text could not be read")?;
    let (text, cut) = tidy_text(&text);
    if text.is_empty() {
        return Err("this page has no text to add".into());
    }
    Ok(PageText {
        url,
        title: title.chars().take(300).collect(),
        text,
        cut,
    })
}

/// The shell testing its own browser in the real window (`WASIFYAI_BROWSER_TEST=<address>`, by
/// hand and in the stage's notes): open the address beside nothing, read the page back as text,
/// try three addresses the browser must not go to, print one line and quit. It does only what the
/// Browser tab's own buttons do.
pub fn self_test(app: AppHandle) {
    let Ok(address) = std::env::var("WASIFYAI_BROWSER_TEST") else {
        return;
    };
    tauri::async_runtime::spawn(async move {
        let wait = |ms| tokio::time::sleep(std::time::Duration::from_millis(ms));
        wait(2500).await;
        let verdict = async {
            browser_show(
                app.clone(),
                Some(address.clone()),
                300.0,
                100.0,
                700.0,
                500.0,
            )
            .await?;
            let mut page = None;
            for _ in 0..40 {
                wait(500).await;
                if let Ok(found) = browser_text(app.clone()).await {
                    page = Some(found);
                    break;
                }
            }
            let page = page.ok_or("the page's text never came")?;
            let view = app.get_webview(LABEL).ok_or("the browser is gone")?;
            // a page tries to leave the web: each of these must be refused by the browser itself
            for bad in [
                "file:///etc/hosts",
                "tauri://localhost/index.html",
                "http://tauri.localhost/",
            ] {
                let _ = view.eval(format!("location.href = {bad:?}"));
                wait(700).await;
                let now = view.url().map(|u| u.to_string()).unwrap_or_default();
                if now != page.url {
                    return Err(format!("the browser went to {now}"));
                }
            }
            // a page asks the shell for the window's token: it must not get an answer
            let _ = view.eval(
                "window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke('engine_session')\
                 .then(s => { document.title = 'LEAKED ' + JSON.stringify(s).length })\
                 .catch(e => { document.title = 'refused: ' + e })",
            );
            wait(1200).await;
            let after = browser_text(app.clone()).await?;
            if after.title.starts_with("LEAKED") {
                return Err("a page was given the window's token".to_string());
            }
            browser_hide(app.clone());
            browser_close(app.clone());
            wait(300).await;
            if app.get_webview(LABEL).is_some() {
                return Err("the browser was not removed".to_string());
            }
            Ok::<String, String>(format!(
                "title={:?} chars={} asked_the_shell={:?}",
                page.title,
                page.text.chars().count(),
                after.title
            ))
        }
        .await;
        match &verdict {
            Ok(detail) => println!("BROWSER_TEST PASS {detail}"),
            Err(why) => println!("BROWSER_TEST FAIL {why}"),
        }
        app.exit(if verdict.is_ok() { 0 } else { 1 });
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_browser_goes_to_web_addresses_only() {
        assert!(page_address("https://developer.mozilla.org/en-US/docs/Web").is_some());
        assert!(page_address("http://localhost:5173/").is_some());
        for bad in [
            "",
            "file:///etc/passwd",
            "tauri://localhost/index.html",
            "javascript:alert(1)",
            "data:text/html,<h1>x</h1>",
            "about:blank",
            "ipc://localhost/engine_session",
            "https://",
            "http://tauri.localhost/",
            "https://tauri.localhost/index.html",
            "http://ipc.localhost/engine_session",
            "http://IPC.LOCALHOST/x",
            "https://example.com/\nfile:///etc/passwd",
        ] {
            assert!(page_address(bad).is_none(), "{bad:?}");
        }
        assert!(page_address(&format!("https://example.com/{}", "a".repeat(4000))).is_none());
    }

    #[test]
    fn what_is_typed_becomes_an_address_or_a_search() {
        let to = |typed: &str| address_from_typed(typed).map(|u| u.to_string());
        assert_eq!(
            to("example.com/a").as_deref(),
            Some("https://example.com/a")
        );
        assert_eq!(
            to(" https://example.com ").as_deref(),
            Some("https://example.com/")
        );
        assert_eq!(
            to("localhost:5173").as_deref(),
            Some("http://localhost:5173/")
        );
        assert_eq!(
            to("date getDay javascript").as_deref(),
            Some("https://duckduckgo.com/?q=date+getDay+javascript")
        );
        assert_eq!(
            to("bread").as_deref(),
            Some("https://duckduckgo.com/?q=bread")
        );
        assert_eq!(to("file:///etc/passwd"), None);
        assert_eq!(to("javascript://x"), None);
        assert_eq!(to("   "), None);
    }

    #[test]
    fn an_area_must_be_inside_a_window() {
        assert!(area(300.0, 96.0, 800.0, 600.0).is_some());
        for (x, y, w, h) in [
            (-1.0, 0.0, 10.0, 10.0),
            (0.0, 0.0, 0.0, 10.0),
            (0.0, 0.0, 10.0, f64::NAN),
            (0.0, f64::INFINITY, 10.0, 10.0),
            (0.0, 0.0, 30_000.0, 10.0),
        ] {
            assert!(area(x, y, w, h).is_none());
        }
    }

    #[test]
    fn a_pages_text_is_tidied_and_cut() {
        assert_eq!(
            tidy_text("One  \n\n\n\nTwo\n \n"),
            ("One\n\nTwo".to_string(), false)
        );
        let long = "é".repeat(MAX_TEXT + 10);
        let (cut, was_cut) = tidy_text(&long);
        assert!(was_cut && cut.chars().count() == MAX_TEXT);
    }

    #[test]
    fn the_scripts_answer_is_read_wrapped_once_or_twice() {
        let once = r#"{"title":"T","text":"Hello"}"#;
        let twice = serde_json::to_string(once).unwrap();
        for raw in [once, twice.as_str()] {
            assert_eq!(
                read_answer(raw),
                Some(("T".to_string(), "Hello".to_string()))
            );
        }
        assert_eq!(read_answer("null"), None);
        assert_eq!(read_answer("not json"), None);
    }
}
