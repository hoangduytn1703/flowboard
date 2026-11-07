fn main() {
    // The UI is served by the agent (http://127.0.0.1:8434), which Tauri treats as a *remote* origin: remote content
    // may call the app's own commands only when a capability lists them by permission (otherwise "Command … not
    // allowed by ACL", seen in 0.1.2). Declaring the commands here generates allow-dflow-check-update /
    // allow-dflow-install-update, granted in capabilities/ui.json.
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["dflow_check_update", "dflow_install_update"]),
        ),
    )
    .expect("failed to run tauri-build");
}
