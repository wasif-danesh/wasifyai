// SPDX-License-Identifier: AGPL-3.0-only
//! Recording a meeting (ADR-0108, stage MT2): the microphone ("You") and the computer's sound
//! ("Others") as one WAV with two channels, 16 kHz, 16-bit, in `<app data>/meetings/recordings`,
//! named `rec-<when>-<id>.wav` (`.part` while recording). The engine makes the meeting from it.
//!
//! The computer's sound on a Mac is a Core Audio process tap on all output in a private aggregate
//! device, after Meetily's capture (MIT, see PROVENANCE.md); on Windows a WASAPI loopback of the
//! default output (not tried yet: no PC here). The microphone is the default input, through cpal.
//!
//! A tap sends nothing while nothing plays, so each piece of sound is placed by the time it came
//! in: a gap is written as silence, and the two channels stay together. While recording, the menu
//! bar shows it, with Stop one click away (decision 6: no question first, no mark on the file).

use serde::Serialize;
use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::JoinHandle;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Emitter, Manager, State};

/// What the file is written at: what the speaker model and the transcribers take.
pub const RATE: u32 = 16_000;
/// How far behind the clock the file is written, so late sound still lands in its place.
const LAG_S: f64 = 0.5;
/// Sound that comes in later than this after the last is after a pause: the pause is silence.
const GAP_S: f64 = 0.2;
const TICK: Duration = Duration::from_millis(100);
/// A microphone that gives exactly nothing this long is one macOS did not allow (a real one hisses).
const MIC_SILENT_S: u64 = 3;
const MIC_NOT_ALLOWED: &str =
    "The microphone gives no sound at all. Allow Wasify AI in System Settings › \
    Privacy & Security › Microphone, then record again.";
/// The file's header is brought up to date this often: a recording the app was closed on is kept.
const FLUSH_EVERY: u32 = 20;

/// Sound as it comes in from one source: when, at what rate, the samples (one channel).
struct Piece {
    at: Instant,
    rate: u32,
    samples: Vec<f32>,
}

type Inbox = Arc<Mutex<Vec<Piece>>>;

fn post(inbox: &Inbox, rate: u32, samples: Vec<f32>) {
    if samples.is_empty() {
        return;
    }
    if let Ok(mut v) = inbox.lock() {
        v.push(Piece {
            at: Instant::now(),
            rate,
            samples,
        });
    }
}

// ---- turning any rate into 16 kHz ----------------------------------------------------------

/// From any rate to `RATE`: each output sample is the mean of the input samples it covers (a
/// box filter, enough for speech), carried across pieces.
struct Resampler {
    rate: u32,
    buf: Vec<f32>,
    pos: f64,
}

impl Resampler {
    fn new() -> Self {
        Self {
            rate: 0,
            buf: Vec::new(),
            pos: 0.0,
        }
    }

    fn push(&mut self, rate: u32, input: &[f32], out: &mut Vec<f32>) {
        if rate == 0 {
            return;
        }
        if rate != self.rate {
            self.rate = rate;
            self.buf.clear();
            self.pos = 0.0;
        }
        self.buf.extend_from_slice(input);
        let step = rate as f64 / RATE as f64;
        while self.pos + step <= self.buf.len() as f64 {
            let a = self.pos as usize;
            let b = ((self.pos + step) as usize).max(a + 1).min(self.buf.len());
            let sum: f32 = self.buf[a..b].iter().sum();
            out.push(sum / (b - a) as f32);
            self.pos += step;
        }
        let used = (self.pos as usize).min(self.buf.len());
        self.buf.drain(..used);
        self.pos -= used as f64;
    }
}

/// One channel of the file: its sound at 16 kHz, waiting to be written, and where it ends.
struct Lane {
    resampler: Resampler,
    queue: VecDeque<f32>,
    /// the position, in frames from the start, of the end of `queue`
    end: f64,
}

impl Lane {
    fn new() -> Self {
        Self {
            resampler: Resampler::new(),
            queue: VecDeque::new(),
            end: 0.0,
        }
    }

    /// Place sound that came in `at` seconds after the start; a pause before it becomes silence.
    fn take(&mut self, at: f64, rate: u32, samples: &[f32]) {
        let mut out = Vec::with_capacity(samples.len());
        self.resampler.push(rate, samples, &mut out);
        let start = at * RATE as f64 - out.len() as f64;
        if start - self.end > GAP_S * RATE as f64 {
            let silence = (start - self.end) as usize;
            self.queue.extend(std::iter::repeat_n(0.0, silence));
            self.end += silence as f64;
        }
        self.end += out.len() as f64;
        self.queue.extend(out);
    }

    /// Silence up to `frame`, where nothing came in.
    fn fill_to(&mut self, frame: u64) {
        if self.end < frame as f64 {
            let n = (frame as f64 - self.end) as usize;
            self.queue.extend(std::iter::repeat_n(0.0, n));
            self.end += n as f64;
        }
    }
}

// ---- the sources ----------------------------------------------------------------------------

mod microphone {
    use super::{post, Inbox};
    use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
    use cpal::{FromSample, SizedSample};

    fn build<T>(
        device: &cpal::Device,
        config: &cpal::StreamConfig,
        inbox: Inbox,
    ) -> Result<cpal::Stream, cpal::BuildStreamError>
    where
        T: SizedSample,
        f32: FromSample<T>,
    {
        let channels = config.channels.max(1) as usize;
        let rate = config.sample_rate.0;
        device.build_input_stream(
            config,
            move |data: &[T], _: &cpal::InputCallbackInfo| {
                let mono: Vec<f32> = data
                    .chunks(channels)
                    .map(|f| f.iter().map(|x| x.to_sample::<f32>()).sum::<f32>() / channels as f32)
                    .collect();
                post(&inbox, rate, mono);
            },
            |e| log::warn!("the microphone stopped: {e}"),
            None,
        )
    }

    /// The default microphone, sending its sound to `inbox` until the stream is dropped. Asking
    /// for it the first time is what makes macOS ask the person (NSMicrophoneUsageDescription).
    pub fn open(inbox: Inbox) -> Result<cpal::Stream, String> {
        let device = cpal::default_host()
            .default_input_device()
            .ok_or("There is no microphone on this computer.")?;
        open_device(&device, inbox, true)
    }

    pub fn open_device(
        device: &cpal::Device,
        inbox: Inbox,
        input: bool,
    ) -> Result<cpal::Stream, String> {
        let supported = if input {
            device.default_input_config()
        } else {
            device.default_output_config()
        }
        .map_err(|e| format!("The sound device could not be opened: {e}"))?;
        let config: cpal::StreamConfig = supported.config();
        let stream = match supported.sample_format() {
            cpal::SampleFormat::F32 => build::<f32>(device, &config, inbox),
            cpal::SampleFormat::I16 => build::<i16>(device, &config, inbox),
            cpal::SampleFormat::U16 => build::<u16>(device, &config, inbox),
            cpal::SampleFormat::I32 => build::<i32>(device, &config, inbox),
            other => {
                return Err(format!(
                    "This sound device gives {other:?}, which is not read."
                ))
            }
        }
        .map_err(|e| format!("The sound device could not be opened: {e}"))?;
        stream
            .play()
            .map_err(|e| format!("The sound device could not start: {e}"))?;
        Ok(stream)
    }
}

/// The computer's own sound, kept running while this is alive. Adapted from Meetily's
/// `audio/capture/core_audio.rs` (MIT), as tried in the MT0 spike.
#[cfg(target_os = "macos")]
mod system {
    use super::{post, Inbox};
    use cidre::{arc, av, cat, cf, core_audio as ca, os};

    struct Ctx {
        format: arc::R<av::AudioFormat>,
        rate: u32,
        inbox: Inbox,
    }

    extern "C" fn io_proc(
        _device: ca::Device,
        _now: &cat::AudioTimeStamp,
        input: &cat::AudioBufList<1>,
        _input_time: &cat::AudioTimeStamp,
        _output: &mut cat::AudioBufList<1>,
        _output_time: &cat::AudioTimeStamp,
        ctx: Option<&mut Ctx>,
    ) -> os::Status {
        if let Some(ctx) = ctx {
            if let Some(buf) = av::AudioPcmBuf::with_buf_list_no_copy(&ctx.format, input, None) {
                if let Some(d) = buf.data_f32_at(0) {
                    post(&ctx.inbox, ctx.rate, d.to_vec());
                }
            }
        }
        os::Status::NO_ERR
    }

    /// Dropped in this order: the device stops, then the context it wrote to, then the tap.
    pub struct Capture {
        _started: ca::hardware::StartedDevice<ca::AggregateDevice>,
        _ctx: Box<Ctx>,
        _tap: ca::TapGuard,
    }

    pub fn open(inbox: Inbox) -> Result<Capture, String> {
        const WHY: &str = "The computer's sound could not be recorded. It needs macOS 14.2 or later, and \
            Wasify AI allowed in System Settings › Privacy & Security › Screen & System Audio Recording.";
        let output = ca::System::default_output_device().map_err(|_| WHY)?;
        let output_uid = output.uid().map_err(|_| WHY)?;
        let tap = ca::TapDesc::with_mono_global_tap_excluding_processes(&cidre::ns::Array::new())
            .create_process_tap()
            .map_err(|_| WHY)?;
        let asbd = tap.asbd().map_err(|_| WHY)?;
        let tap_uid = tap.uid().map_err(|_| WHY)?;
        let sub_tap = cf::DictionaryOf::with_keys_values(
            &[ca::sub_device_keys::uid()],
            &[tap_uid.as_type_ref()],
        );
        let desc = cf::DictionaryOf::with_keys_values(
            &[
                ca::aggregate_device_keys::is_private(),
                ca::aggregate_device_keys::is_stacked(),
                ca::aggregate_device_keys::tap_auto_start(),
                ca::aggregate_device_keys::name(),
                ca::aggregate_device_keys::main_sub_device(),
                ca::aggregate_device_keys::uid(),
                ca::aggregate_device_keys::tap_list(),
            ],
            &[
                cf::Boolean::value_true().as_type_ref(),
                cf::Boolean::value_false(),
                cf::Boolean::value_true(),
                cf::str!(c"Wasify AI meeting").as_type_ref(),
                &output_uid,
                &cf::Uuid::new().to_cf_string(),
                &cf::ArrayOf::from_slice(&[sub_tap.as_ref()]),
            ],
        );
        let format = av::AudioFormat::with_asbd(&asbd).ok_or(WHY)?;
        let mut ctx = Box::new(Ctx {
            format,
            rate: asbd.sample_rate as u32,
            inbox,
        });
        let device = ca::AggregateDevice::with_desc(&desc).map_err(|_| WHY)?;
        let proc_id = device
            .create_io_proc_id(io_proc, Some(&mut ctx))
            .map_err(|_| WHY)?;
        let started = ca::device_start(device, Some(proc_id)).map_err(|_| WHY)?;
        Ok(Capture {
            _started: started,
            _ctx: ctx,
            _tap: tap,
        })
    }

    pub const SUPPORTED: bool = true;
}

/// Windows: the default output, read back through WASAPI's loopback (cpal opens an output device
/// as an input for that). Written to the same plan as the Mac's; not run yet, there is no PC here.
#[cfg(windows)]
mod system {
    use super::{microphone, Inbox};
    use cpal::traits::HostTrait;

    pub struct Capture {
        _stream: cpal::Stream,
    }

    pub fn open(inbox: Inbox) -> Result<Capture, String> {
        let device = cpal::default_host()
            .default_output_device()
            .ok_or("There is no sound output on this computer to record.")?;
        Ok(Capture {
            _stream: microphone::open_device(&device, inbox, false)?,
        })
    }

    pub const SUPPORTED: bool = true;
}

#[cfg(not(any(target_os = "macos", windows)))]
mod system {
    use super::Inbox;

    pub struct Capture;

    pub fn open(_inbox: Inbox) -> Result<Capture, String> {
        Err("Recording the computer's sound is not built for Linux yet: only the microphone is recorded."
            .into())
    }

    pub const SUPPORTED: bool = false;
}

// ---- the recording --------------------------------------------------------------------------

/// What the window and the menu bar read while recording.
#[derive(Default)]
struct Live {
    levels: [AtomicU32; 2],
    others: AtomicBool,
    mic: AtomicBool,
    frames: std::sync::atomic::AtomicU64,
    problems: Mutex<Vec<String>>,
}

struct Active {
    name: String,
    stop: Arc<AtomicBool>,
    live: Arc<Live>,
    thread: Option<JoinHandle<Result<Recorded, String>>>,
}

#[derive(Default)]
pub struct Recorder {
    dir: Mutex<Option<PathBuf>>,
    active: Mutex<Option<Active>>,
}

#[derive(Serialize, Clone, Debug)]
pub struct Recorded {
    /// the file's name in the recordings folder, to hand the engine
    pub name: String,
    pub seconds: f64,
    /// whether the computer's sound was recorded
    pub others: bool,
    pub problems: Vec<String>,
}

#[derive(Serialize)]
pub struct RecordState {
    /// the computer's sound can be recorded here (a Mac, Windows)
    pub others_supported: bool,
    pub recording: bool,
    pub name: Option<String>,
    pub seconds: f64,
    /// the loudness of the microphone and of the computer's sound now, 0 to 1
    pub levels: [f32; 2],
    pub mic: bool,
    pub others: bool,
    pub problems: Vec<String>,
}

impl Recorder {
    /// The app data folder: recordings go to its `meetings/recordings`.
    pub fn set_dir(&self, data_dir: &Path) {
        *self.dir.lock().unwrap() = Some(data_dir.join("meetings").join("recordings"));
    }

    fn state(&self) -> RecordState {
        let active = self.active.lock().unwrap();
        match active.as_ref() {
            Some(a) => RecordState {
                others_supported: system::SUPPORTED,
                recording: true,
                name: Some(a.name.clone()),
                seconds: a.live.frames.load(Ordering::Relaxed) as f64 / RATE as f64,
                levels: [0, 1].map(|i| f32::from_bits(a.live.levels[i].load(Ordering::Relaxed))),
                mic: a.live.mic.load(Ordering::Relaxed),
                others: a.live.others.load(Ordering::Relaxed),
                problems: a.live.problems.lock().unwrap().clone(),
            },
            None => RecordState {
                others_supported: system::SUPPORTED,
                recording: false,
                name: None,
                seconds: 0.0,
                levels: [0.0, 0.0],
                mic: false,
                others: false,
                problems: vec![],
            },
        }
    }

    fn start(&self, app: &AppHandle) -> Result<RecordState, String> {
        let mut active = self.active.lock().unwrap();
        if active.is_some() {
            return Err("A meeting is being recorded already.".into());
        }
        let dir = self
            .dir
            .lock()
            .unwrap()
            .clone()
            .ok_or("The app is still starting. Try again in a moment.")?;
        std::fs::create_dir_all(&dir)
            .map_err(|e| format!("The recordings folder could not be made: {e}"))?;
        let name = file_name();
        let part = dir.join(format!("{name}.part"));
        let done = dir.join(&name);
        let stop = Arc::new(AtomicBool::new(false));
        let live = Arc::new(Live::default());
        // the sources open on the recording's own thread (a cpal stream may not move between
        // threads); it says whether they opened before this returns
        let (ready_tx, ready_rx) = std::sync::mpsc::channel::<Result<(), String>>();
        let thread = {
            let (stop, live, app) = (stop.clone(), live.clone(), app.clone());
            std::thread::Builder::new()
                .name("meeting-recorder".into())
                .spawn(move || record(part, done, stop, live, ready_tx, app))
                .map_err(|e| format!("The recording could not start: {e}"))?
        };
        match ready_rx.recv_timeout(Duration::from_secs(20)) {
            Ok(Ok(())) => {}
            Ok(Err(e)) => {
                let _ = thread.join();
                return Err(e);
            }
            Err(_) => {
                stop.store(true, Ordering::SeqCst);
                return Err("The sound devices did not answer. Try again.".into());
            }
        }
        *active = Some(Active {
            name,
            stop,
            live,
            thread: Some(thread),
        });
        drop(active);
        tray::show(app);
        Ok(self.state())
    }

    fn stop(&self, app: &AppHandle) -> Result<Recorded, String> {
        let taken = self.active.lock().unwrap().take();
        let Some(mut a) = taken else {
            return Err("Nothing is being recorded.".into());
        };
        a.stop.store(true, Ordering::SeqCst);
        let out = match a.thread.take().map(|t| t.join()) {
            Some(Ok(r)) => r,
            _ => Err("The recording stopped with a fault.".into()),
        };
        tray::hide(app);
        out
    }
}

fn file_name() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let tag: u32 = rand::random();
    format!("rec-{secs}-{tag:08x}.wav")
}

fn rms(samples: impl Iterator<Item = f32>) -> f32 {
    let (mut sum, mut n) = (0.0f64, 0usize);
    for x in samples {
        sum += (x as f64) * (x as f64);
        n += 1;
    }
    if n == 0 {
        0.0
    } else {
        ((sum / n as f64).sqrt() as f32).min(1.0)
    }
}

/// The recording's thread: opens the sources, writes the file until `stop`, finishes it.
fn record(
    part: PathBuf,
    done: PathBuf,
    stop: Arc<AtomicBool>,
    live: Arc<Live>,
    ready: std::sync::mpsc::Sender<Result<(), String>>,
    app: AppHandle,
) -> Result<Recorded, String> {
    let mic_in: Inbox = Arc::default();
    let sys_in: Inbox = Arc::default();
    let mic = microphone::open(mic_in.clone());
    let sys = system::open(sys_in.clone());
    let mut problems = vec![];
    if let Err(e) = &mic {
        problems.push(e.clone());
    }
    if let Err(e) = &sys {
        problems.push(e.clone());
    }
    if mic.is_err() && sys.is_err() {
        let _ = ready.send(Err(problems.join(" ")));
        return Err(problems.join(" "));
    }
    live.mic.store(mic.is_ok(), Ordering::Relaxed);
    live.others.store(sys.is_ok(), Ordering::Relaxed);
    *live.problems.lock().unwrap() = problems.clone();

    let spec = hound::WavSpec {
        channels: 2,
        sample_rate: RATE,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut wav = match hound::WavWriter::create(&part, spec) {
        Ok(w) => w,
        Err(e) => {
            let why = format!("The recording file could not be made: {e}");
            let _ = ready.send(Err(why.clone()));
            return Err(why);
        }
    };
    let started = Instant::now();
    let _ = ready.send(Ok(()));

    let mut lanes = [Lane::new(), Lane::new()];
    let mut written: u64 = 0;
    let mut ticks: u32 = 0;
    let mut last_second = u64::MAX;
    let mut failed: Option<String> = None;
    let mut mic_heard = false;
    loop {
        let ending = stop.load(Ordering::SeqCst);
        if !ending {
            std::thread::sleep(TICK);
        }
        for (lane, inbox) in lanes.iter_mut().zip([&mic_in, &sys_in]) {
            let pieces = std::mem::take(&mut *inbox.lock().unwrap());
            for p in pieces {
                let at = p.at.saturating_duration_since(started).as_secs_f64();
                lane.take(at, p.rate, &p.samples);
            }
        }
        let now = started.elapsed().as_secs_f64();
        let target = ((if ending { now } else { now - LAG_S }).max(0.0) * RATE as f64) as u64;
        if target > written {
            for lane in lanes.iter_mut() {
                lane.fill_to(target);
            }
            let n = (target - written) as usize;
            let a: Vec<f32> = lanes[0].queue.drain(..n).collect();
            let b: Vec<f32> = lanes[1].queue.drain(..n).collect();
            mic_heard = mic_heard || a.iter().any(|x| *x != 0.0);
            if !mic_heard
                && live.mic.load(Ordering::Relaxed)
                && target >= MIC_SILENT_S * RATE as u64
            {
                live.mic.store(false, Ordering::Relaxed);
                live.problems.lock().unwrap().push(MIC_NOT_ALLOWED.into());
            }
            live.levels[0].store(rms(a.iter().copied()).to_bits(), Ordering::Relaxed);
            live.levels[1].store(rms(b.iter().copied()).to_bits(), Ordering::Relaxed);
            for (x, y) in a.iter().zip(b.iter()) {
                let ok = wav
                    .write_sample((x.clamp(-1.0, 1.0) * 32767.0) as i16)
                    .and_then(|_| wav.write_sample((y.clamp(-1.0, 1.0) * 32767.0) as i16));
                if let Err(e) = ok {
                    failed = Some(format!("The recording could not be written: {e}"));
                    break;
                }
            }
            written = target;
            live.frames.store(written, Ordering::Relaxed);
        }
        ticks += 1;
        if ticks.is_multiple_of(FLUSH_EVERY) {
            let _ = wav.flush();
        }
        let second = written / RATE as u64;
        if second != last_second {
            last_second = second;
            tray::tick(&app, second);
        }
        if ending || failed.is_some() {
            break;
        }
    }
    drop(sys);
    drop(mic);
    wav.finalize()
        .map_err(|e| format!("The recording could not be finished: {e}"))?;
    if let Some(e) = failed {
        return Err(e);
    }
    std::fs::rename(&part, &done).map_err(|e| format!("The recording could not be kept: {e}"))?;
    Ok(Recorded {
        name: done
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_default(),
        seconds: written as f64 / RATE as f64,
        others: live.others.load(Ordering::Relaxed),
        problems: live.problems.lock().unwrap().clone(),
    })
}

// ---- the menu bar while recording -----------------------------------------------------------

#[cfg(target_os = "macos")]
mod tray {
    use tauri::menu::{Menu, MenuItem};
    use tauri::tray::TrayIconBuilder;
    use tauri::{AppHandle, Emitter};

    const ID: &str = "meeting-recording";

    pub fn show(app: &AppHandle) {
        let app2 = app.clone();
        let _ = app.run_on_main_thread(move || {
            let app = &app2;
            if app.tray_by_id(ID).is_some() {
                return;
            }
            let made = (|| -> tauri::Result<()> {
                let what =
                    MenuItem::with_id(app, "rec-what", "Recording a meeting", false, None::<&str>)?;
                let stop =
                    MenuItem::with_id(app, "rec-stop", "Stop recording", true, None::<&str>)?;
                let open =
                    MenuItem::with_id(app, "rec-open", "Open Wasify AI", true, None::<&str>)?;
                let menu = Menu::with_items(app, &[&what, &stop, &open])?;
                let mut tray = TrayIconBuilder::with_id(ID)
                    .tooltip("Wasify AI is recording a meeting")
                    .title("● 0:00")
                    .menu(&menu)
                    .show_menu_on_left_click(true)
                    .on_menu_event(|app, event| match event.id().as_ref() {
                        "rec-stop" => super::stop_from_menu(app),
                        "rec-open" => super::show_window(app),
                        _ => {}
                    });
                if let Some(icon) = app.default_window_icon() {
                    tray = tray.icon(icon.clone());
                }
                tray.build(app).map(|_| ())
            })();
            if let Err(e) = made {
                log::warn!("the recording's menu bar item could not be made: {e}");
            }
        });
    }

    pub fn tick(app: &AppHandle, second: u64) {
        let app2 = app.clone();
        let _ = app.run_on_main_thread(move || {
            if let Some(tray) = app2.tray_by_id(ID) {
                let _ = tray.set_title(Some(format!("● {}", super::clock(second))));
            }
        });
        let _ = app.emit("meeting-recording", second);
    }

    pub fn hide(app: &AppHandle) {
        let app2 = app.clone();
        let _ = app.run_on_main_thread(move || {
            let _ = app2.remove_tray_by_id(ID);
        });
    }
}

#[cfg(not(target_os = "macos"))]
mod tray {
    use tauri::{AppHandle, Emitter};

    // the window shows the recording plainly; the tray item is built for the Mac only, like the
    // app's other menu bar item (elsewhere it needs system packages the builds do not have)
    pub fn show(_app: &AppHandle) {}
    pub fn tick(app: &AppHandle, second: u64) {
        let _ = app.emit("meeting-recording", second);
    }
    pub fn hide(_app: &AppHandle) {}
}

fn clock(second: u64) -> String {
    let (h, m, s) = (second / 3600, second / 60 % 60, second % 60);
    if h > 0 {
        format!("{h}:{m:02}:{s:02}")
    } else {
        format!("{m}:{s:02}")
    }
}

#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn show_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// Stop from the menu bar: the recording is finished here and handed to the window, which asks
/// the engine to make the meeting (a recording the window misses waits in the folder, and the
/// Record screen offers it).
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn stop_from_menu(app: &AppHandle) {
    let app = app.clone();
    std::thread::spawn(move || {
        let recorder = app.state::<Recorder>();
        match recorder.stop(&app) {
            Ok(done) => {
                let _ = app.emit("meeting-recorded", done);
            }
            Err(e) => {
                let _ = app.emit("meeting-record-failed", e);
            }
        }
        show_window(&app);
    });
}

// ---- what the window calls ------------------------------------------------------------------

#[tauri::command]
pub fn meeting_record_state(recorder: State<'_, Recorder>) -> RecordState {
    recorder.state()
}

/// `async` so the wait for the devices (and macOS's permission questions) is off the main thread.
#[tauri::command]
pub async fn meeting_record_start(app: AppHandle) -> Result<RecordState, String> {
    tauri::async_runtime::spawn_blocking(move || app.state::<Recorder>().start(&app))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn meeting_record_stop(app: AppHandle) -> Result<Recorded, String> {
    tauri::async_runtime::spawn_blocking(move || app.state::<Recorder>().stop(&app))
        .await
        .map_err(|e| e.to_string())?
}

/// A recording still on when the app quits is finished, so it is there to be made into a meeting.
pub fn finish_on_exit(app: &AppHandle) {
    let recorder = app.state::<Recorder>();
    if recorder.active.lock().map(|a| a.is_some()).unwrap_or(false) {
        let _ = recorder.stop(app);
    }
}

/// The shell recording for real (`WASIFYAI_RECORD_TEST=<seconds>`, with `WASIFYAI_DATA_DIR` naming
/// a throwaway folder): records that long, prints one line about the file and quits.
pub fn self_test(app: AppHandle) {
    let Some(secs) = std::env::var("WASIFYAI_RECORD_TEST")
        .ok()
        .and_then(|s| s.parse::<f64>().ok())
    else {
        return;
    };
    std::thread::spawn(move || {
        let recorder = app.state::<Recorder>();
        let line = match recorder.start(&app) {
            Ok(_) => {
                std::thread::sleep(Duration::from_secs_f64(secs));
                match recorder.stop(&app) {
                    Ok(r) => format!(
                        "RECORD_TEST ok name={} seconds={:.2} others={} problems={:?}",
                        r.name, r.seconds, r.others, r.problems
                    ),
                    Err(e) => format!("RECORD_TEST failed stop: {e}"),
                }
            }
            Err(e) => format!("RECORD_TEST failed start: {e}"),
        };
        println!("{line}");
        app.exit(0);
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_48k_tone_becomes_16k_at_the_same_pitch() {
        let mut r = Resampler::new();
        let mut out = vec![];
        let input: Vec<f32> = (0..48_000)
            .map(|i| (2.0 * std::f32::consts::PI * 440.0 * i as f32 / 48_000.0).sin())
            .collect();
        for chunk in input.chunks(480) {
            r.push(48_000, chunk, &mut out);
        }
        assert!((out.len() as i64 - 16_000).abs() <= 1, "{}", out.len());
        // the tone crosses zero 880 times a second at any rate
        let crossings = out.windows(2).filter(|w| w[0] <= 0.0 && w[1] > 0.0).count();
        assert!((crossings as i64 - 440).abs() <= 2, "{crossings}");
    }

    #[test]
    fn odd_rates_and_tiny_pieces_keep_the_length() {
        let mut r = Resampler::new();
        let mut out = vec![];
        for _ in 0..441 {
            r.push(44_100, &[0.5; 100], &mut out);
        }
        assert!((out.len() as i64 - 16_000).abs() <= 1, "{}", out.len());
        assert!(out.iter().all(|x| (x - 0.5).abs() < 1e-6));
    }

    #[test]
    fn a_pause_in_the_computers_sound_is_written_as_silence_in_its_place() {
        let mut lane = Lane::new();
        // 0.5 s of sound, then nothing for 2 s, then 0.5 s that came in at 3.0 s
        lane.take(0.5, RATE, &vec![0.3; 8_000]);
        lane.take(3.0, RATE, &vec![0.6; 8_000]);
        assert_eq!(lane.queue.len(), 48_000);
        assert_eq!(lane.queue[7_999], 0.3);
        assert_eq!(lane.queue[8_000], 0.0);
        assert_eq!(lane.queue[39_999], 0.0);
        assert_eq!(lane.queue[40_000], 0.6);
    }

    #[test]
    fn steady_sound_with_jitter_is_not_broken_up() {
        let mut lane = Lane::new();
        let mut at = 0.0;
        for i in 0..100 {
            at += 0.01 + if i % 2 == 0 { 0.004 } else { -0.004 };
            lane.take(at, RATE, &vec![0.1; 160]);
        }
        assert!(lane.queue.iter().all(|x| *x == 0.1));
    }

    #[test]
    fn silence_fills_up_to_the_clock_when_nothing_came_in() {
        let mut lane = Lane::new();
        lane.fill_to(16_000);
        assert_eq!(lane.queue.len(), 16_000);
        lane.take(1.5, RATE, &vec![0.2; 8_000]); // came in on time after the filled second
        assert_eq!(lane.queue.len(), 24_000);
    }

    #[test]
    fn the_clock_reads_like_a_timer() {
        assert_eq!(clock(5), "0:05");
        assert_eq!(clock(754), "12:34");
        assert_eq!(clock(3_725), "1:02:05");
    }
}
