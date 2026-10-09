//! `comfy::missing` against a stand-in ComfyUI: what `bromigos target probe` and `bromigos art
//! make` read before they pick a workflow (its model files, its nodes, the card's VRAM).

use bromigos_art::comfy;
use serde_json::json;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

async fn lab(server: &MockServer) {
    let gib = 1u64 << 30;
    Mock::given(method("GET"))
        .and(path("/system_stats"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({
            "system": {"comfyui_version": "0.38.0"},
            "devices": [{"vram_total": 32 * gib, "vram_free": 18 * gib}]
        })))
        .mount(server)
        .await;
    for (folder, files) in [
        (
            "diffusion_models",
            json!(["wan2.2_ti2v_5B_fp16.safetensors"]),
        ),
        (
            "text_encoders",
            json!(["umt5_xxl_fp8_e4m3fn_scaled.safetensors"]),
        ),
        ("vae", json!(["wan2.2_vae.safetensors"])),
    ] {
        Mock::given(method("GET"))
            .and(path(format!("/models/{folder}")))
            .respond_with(ResponseTemplate::new(200).set_body_json(files))
            .mount(server)
            .await;
    }
    for node in [
        "Wan22ImageToVideoLatent",
        "ReplaceVideoLatentFrames",
        "LatentCut",
        "SetLatentNoiseMask",
        "CreateVideo",
        "SaveVideo",
        "KSamplerAdvanced",
    ] {
        Mock::given(method("GET"))
            .and(path(format!("/object_info/{node}")))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({node: {}})))
            .mount(server)
            .await;
    }
    // a node the server doesn't have: ComfyUI answers {}
    Mock::given(method("GET"))
        .and(path("/object_info/WanFirstLastFrameToVideo"))
        .respond_with(ResponseTemplate::new(200).set_body_json(json!({})))
        .mount(server)
        .await;
}

#[tokio::test]
async fn the_5b_is_ready_and_the_14b_lacks_its_experts() {
    let server = MockServer::start().await;
    lab(&server).await;
    let http = comfy::client().unwrap();

    let w = comfy::workflow("wan2.2-ti2v-5b").unwrap();
    let m = comfy::missing(&http, &server.uri(), &w).await.unwrap();
    assert!(m.ready() && m.fits(&w), "{m:?}");
    assert_eq!(m.version, "0.38.0");
    assert_eq!((m.vram_free_gib, m.vram_total_gib), (18.0, 32.0));
    assert!(m.describe(&w).starts_with("wan2.2-ti2v-5b ready, peak"));

    let w = comfy::workflow("wan2.2-i2v-a14b").unwrap();
    let m = comfy::missing(&http, &server.uri(), &w).await.unwrap();
    assert!(!m.ready());
    assert_eq!(
        m.files,
        [
            "diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
            "diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
            "vae/wan_2.1_vae.safetensors"
        ]
    );
    assert_eq!(m.nodes, ["WanFirstLastFrameToVideo"]);
    assert!(m.describe(&w).contains("missing diffusion_models/"));
}

#[tokio::test]
async fn a_peak_over_the_card_does_not_fit() {
    let server = MockServer::start().await;
    lab(&server).await;
    let http = comfy::client().unwrap();
    let mut w = comfy::workflow("wan2.2-ti2v-5b").unwrap();
    w.vram_gib = Some(40.0);
    let m = comfy::missing(&http, &server.uri(), &w).await.unwrap();
    assert!(m.ready() && !m.fits(&w));
    assert!(m.describe(&w).contains("needs 40.0 GiB, the card has 32.0"));
    // an unmeasured workflow fits
    w.vram_gib = None;
    assert!(m.fits(&w));
}
