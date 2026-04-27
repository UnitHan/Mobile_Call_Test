pub mod utils;
pub mod types;
pub mod state;
pub mod env_cmd;
pub mod device_cmd;
pub mod appium_cmd;
pub mod test_cmd;
pub mod db;
pub mod db_cmd;
pub mod util_cmd;
pub mod secret_cmd;
pub mod schedule_cmd;

use state::GLOBAL_APP;
use tauri::Manager;
use device_cmd::{connect_android_wireless, disconnect_android_wireless, get_android_ip,
                  check_iphone_connection, list_android_devices, list_ios_devices,
                  install_wda, start_android_watchdog, stop_android_watchdog,
                  get_app_versions};
use appium_cmd::{start_appium_server, stop_appium_server, start_tc_appium_servers, stop_tc_appium_servers};
use test_cmd::{run_ixio_test, stop_test, list_audio_devices, play_test_tone, run_dropout_analysis, open_report, read_file_base64, save_xlsx, save_session_report, generate_mos_report, scan_audio_interfaces, save_audio_interface_config, get_audio_interface_config};
use env_cmd::{check_environment, setup_python_env};
use db_cmd::{db_save_result, db_save_session, db_query_results, db_query_result_detail, db_export_stats, db_batch_save_results, db_get_session_progress, db_get_queue_estimate, db_find_recent_session, db_update_mos_report_path, db_load_snapshot};
use util_cmd::{clear_result_files, send_stats_email, save_temp_file, save_temp_text};
use secret_cmd::{store_secret, get_secret, delete_secret};
use schedule_cmd::{load_schedules, save_schedules, load_speaker_config, save_speaker_config, load_tc_speaker_config, save_tc_speaker_config};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            *GLOBAL_APP.lock().unwrap() = Some(app.handle().clone());

            // DB 초기화 — app data dir에 ixio_results.db 생성
            let data_dir = app.handle().path().app_data_dir()
                .expect("app_data_dir 없음");
            std::fs::create_dir_all(&data_dir).ok();
            schedule_cmd::init_schedules_path(&data_dir);
            db_cmd::init_db(data_dir);

            #[cfg(target_os = "macos")]
            {
                use tauri::menu::{AboutMetadata, MenuBuilder, PredefinedMenuItem, SubmenuBuilder};
                let handle = app.handle();
                let icon = app.default_window_icon().cloned();
                // 신호등 영역 타이틀 텍스트 제거
                if let Some(win) = app.get_webview_window("main") {
                    let _ = win.set_title("");
                }
                let about = AboutMetadata {
                    name: Some("ixi-O 음성통화 테스트 자동화".to_string()),
                    version: Some(env!("CARGO_PKG_VERSION").to_string()),
                    copyright: Some("© 2026 QA Bulls".to_string()),
                    icon,
                    ..Default::default()
                };
                let about_item = PredefinedMenuItem::about(handle, None, Some(about))?;
                let quit_item  = PredefinedMenuItem::quit(handle, None)?;
                let app_submenu = SubmenuBuilder::new(handle, "ixi-O 음성통화 테스트 자동화")
                    .item(&about_item)
                    .separator()
                    .item(&quit_item)
                    .build()?;
                let menu = MenuBuilder::new(handle)
                    .item(&app_submenu)
                    .build()?;
                app.set_menu(menu)?;
            }

            Ok(())
        })
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            connect_android_wireless,
            disconnect_android_wireless,
            get_android_ip,
            check_iphone_connection,
            list_android_devices,
            list_ios_devices,
            install_wda,
            start_android_watchdog,
            stop_android_watchdog,
            start_appium_server,
            stop_appium_server,
            start_tc_appium_servers,
            stop_tc_appium_servers,
            run_ixio_test,
            stop_test,
            list_audio_devices,
            scan_audio_interfaces,
            save_audio_interface_config,
            get_audio_interface_config,
            play_test_tone,
            run_dropout_analysis,
            generate_mos_report,
            open_report,
            read_file_base64,
            save_xlsx,
            save_session_report,
            check_environment,
            setup_python_env,
            get_app_versions,
            db_save_result,
            db_save_session,
            db_query_results,
            db_query_result_detail,
            db_export_stats,
            db_batch_save_results,
            db_get_session_progress,
            db_get_queue_estimate,
            db_find_recent_session,
            db_update_mos_report_path,
            db_load_snapshot,
            clear_result_files,
            send_stats_email,
            save_temp_file,
            save_temp_text,
            store_secret,
            get_secret,
            delete_secret,
            load_schedules,
            save_schedules,
            load_speaker_config,
            save_speaker_config,
            load_tc_speaker_config,
            save_tc_speaker_config,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
