//! Development probe: read a window through Accessibility and report what
//! came back and how long it took.
//!
//!     cargo run --example ax_probe            # the frontmost app
//!     cargo run --example ax_probe -- <pid>   # a specific app, without focusing it
use std::time::Instant;

fn cpu_ms() -> f64 {
    let mut usage: libc::rusage = unsafe { std::mem::zeroed() };
    unsafe { libc::getrusage(libc::RUSAGE_SELF, &mut usage) };
    (usage.ru_utime.tv_sec as f64 + usage.ru_stime.tv_sec as f64) * 1000.0
        + (usage.ru_utime.tv_usec as f64 + usage.ru_stime.tv_usec as f64) / 1000.0
}

fn main() {
    println!("accessibility trusted: {}", app_lib::ax::trusted());
    let pid: u64 = match std::env::args().nth(1) {
        Some(p) => p.parse().expect("pid"),
        None => {
            let w = active_win_pos_rs::get_active_window().expect("no active window");
            println!("front: {} | {}", w.app_name, w.title);
            w.process_id
        }
    };
    let chromium = std::env::args().nth(2).is_some_and(|a| a == "chromium");
    for run in 0..4 {
        let (c, t) = (cpu_ms(), Instant::now());
        let result = app_lib::ax::read_front_window(pid, chromium);
        let (ms, cpu) = (t.elapsed().as_secs_f64() * 1000.0, cpu_ms() - c);
        match result {
            Some(r) => {
                println!(
                    "run {run}: {ms:.0} ms, {cpu:.0} ms cpu, kind={} url={} chars={} words={}",
                    r.kind, r.url, r.text.len(), r.text.split_whitespace().count()
                );
                if run == 3 {
                    println!("--- first 400 chars ---\n{}", r.text.chars().take(400).collect::<String>());
                }
            }
            None => println!("run {run}: nothing ({ms:.0} ms)"),
        }
        std::thread::sleep(std::time::Duration::from_millis(800));
    }
}
