//! `comfy::unload_if_idle` against a stand-in ComfyUI: a clip upscale asks an idle server to
//! unload its models before the job (SeedVR2's temporal chunks are sized to the free VRAM),
//! and leaves a busy one alone.

use std::time::Duration;

use bromigos_art::comfy;
use serde_json::json;
use wiremock::matchers::{body_json, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

const GIB: u64 = 1 << 30;

async fn lab(server: &MockServer, running: serde_json::Value, free_after: u64) {
    Mock::given(method("GET"))
        .and(path("/queue"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(json!({"queue_running": running, "queue_pending": []})),
        )
        .mount(server)
        .await;
    // the first look sees SeedVR2 resident (8.9 GiB free), every later one the card after /free
    let stats = |free: u64| {
        ResponseTemplate::new(200).set_body_json(json!({
            "system": {"comfyui_version": "0.38.0"},
            "devices": [{"vram_total": 32 * GIB, "vram_free": free}]
        }))
    };
    Mock::given(method("GET"))
        .and(path("/system_stats"))
        .respond_with(stats(89 * GIB / 10))
        .up_to_n_times(1)
        .mount(server)
        .await;
    Mock::given(method("GET"))
        .and(path("/system_stats"))
        .respond_with(stats(free_after))
        .mount(server)
        .await;
}

#[tokio::test]
async fn an_idle_server_unloads_and_the_wait_ends_once_the_vram_is_back() {
    let server = MockServer::start().await;
    lab(&server, json!([]), 167 * GIB / 10).await;
    Mock::given(method("POST"))
        .and(path("/free"))
        .and(body_json(
            json!({"unload_models": true, "free_memory": true}),
        ))
        .respond_with(ResponseTemplate::new(200))
        .expect(1)
        .mount(&server)
        .await;
    let http = comfy::client().unwrap();
    let t = std::time::Instant::now();
    let freed = comfy::unload_if_idle(&http, &server.uri(), Duration::from_secs(30))
        .await
        .unwrap()
        .unwrap();
    assert!((freed - 7.8).abs() < 0.01, "{freed}");
    // risen and held: no waiting out the settle time
    assert!(t.elapsed() < Duration::from_secs(5), "{:?}", t.elapsed());
}

#[tokio::test]
async fn a_busy_server_is_left_alone() {
    let server = MockServer::start().await;
    lab(
        &server,
        json!([[0, "a-pulpo-job", {}, {}, []]]),
        167 * GIB / 10,
    )
    .await;
    Mock::given(method("POST"))
        .and(path("/free"))
        .respond_with(ResponseTemplate::new(200))
        .expect(0)
        .mount(&server)
        .await;
    let http = comfy::client().unwrap();
    let r = comfy::unload_if_idle(&http, &server.uri(), Duration::from_secs(1)).await;
    assert_eq!(r.unwrap(), None);
}

#[test]
fn only_the_clip_upscale_unloads_first() {
    for (id, want) in [
        ("seedvr2-7b-video", true),
        ("seedvr2-7b", false),
        ("qwen-image-2.1", false),
    ] {
        // the built-in copy: an installed one in /usr/share/bromigos may be older
        let text = comfy::BUILTIN.iter().find(|(n, _)| *n == id).unwrap().1;
        let w = comfy::Workflow::parse(id, text).unwrap();
        assert_eq!(w.unload_first(), want, "{id}");
    }
}
