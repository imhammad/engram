//! Development probe: read the frontmost window through Accessibility and
//! report what came back and how long it took.
//!
//!     cargo run --example ax_probe
use std::time::Instant;

fn cpu_ms() -> f64 {
    let mut usage: libc::rusage = unsafe { std::mem::zeroed() };
    unsafe { libc::getrusage(libc::RUSAGE_SELF, &mut usage) };
    (usage.ru_utime.tv_sec as f64 + usage.ru_stime.tv_sec as f64) * 1000.0
        + (usage.ru_utime.tv_usec as f64 + usage.ru_stime.tv_usec as f64) / 1000.0
}

fn main() {
    println!("accessibility trusted: {}", app_lib::ax::trusted());
    let window = active_win_pos_rs::get_active_window().expect("no active window");
    println!("front: {} | {}", window.app_name, window.title);
    let chromium = window.app_name.contains("Chrome") || window.app_name.contains("Edge") || window.app_name.contains("Brave");
    for run in 0..3 {
        let (c, t) = (cpu_ms(), Instant::now());
        let result = app_lib::ax::read_front_window(window.process_id, chromium);
        let (ms, cpu) = (t.elapsed().as_secs_f64() * 1000.0, cpu_ms() - c);
        match result {
            Some(r) => println!(
                "run {run}: {ms:.0} ms, {cpu:.0} ms cpu, kind={} url={} chars={} words={}",
                r.kind, r.url, r.text.len(), r.text.split_whitespace().count()
            ),
            None => println!("run {run}: nothing ({ms:.0} ms)"),
        }
    }
}
