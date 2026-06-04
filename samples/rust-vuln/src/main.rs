// Rust vulnerable dependencies sample
// CVEs: git2 0.13, remove_dir_all 0.5.2, tokio 1.8.0, time 0.1.42

use std::path::Path;

fn main() {
    // CVE-2022-21658: remove_dir_all race condition
    let _ = remove_dir_all::remove_dir_all(Path::new("/tmp/test"));

    println!("Rust vuln sample");
}
