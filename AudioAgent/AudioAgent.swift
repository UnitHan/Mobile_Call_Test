import SwiftUI
import AVFoundation

@main
struct AudioAgentApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}

struct ContentView: View {
    @State private var player: AVAudioPlayer?
    @State private var status = "대기 중..."
    
    var body: some View {
        VStack(spacing: 20) {
            Text("Audio Agent")
                .font(.largeTitle)
                .padding()
            
            Text(status)
                .foregroundColor(.gray)
            
            Button("URL에서 재생") {
                playFromURL()
            }
            .buttonStyle(.borderedProminent)
            .padding()
        }
        .onAppear {
            setupAudioSession()
            startHTTPServer()
        }
    }
    
    func setupAudioSession() {
        do {
            let session = AVAudioSession.sharedInstance()
            // 통화 중에도 오디오 재생 가능하도록 설정
            try session.setCategory(.playback, mode: .voiceChat, options: [.mixWithOthers])
            try session.setActive(true)
            status = "✅ 오디오 세션 준비 완료"
        } catch {
            status = "❌ 오디오 세션 실패: \(error)"
        }
    }
    
    func startHTTPServer() {
        // 간단한 HTTP 폴링 서버
        Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in
            checkForAudioCommand()
        }
    }
    
    func checkForAudioCommand() {
        // Mac의 HTTP 서버에서 명령 확인
        guard let url = URL(string: "http://192.168.219.121:8800/command.txt") else { return }
        
        URLSession.shared.dataTask(with: url) { data, response, error in
            guard let data = data,
                  let command = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines),
                  command.hasPrefix("play:") else {
                return
            }
            
            // play:speaker_2.wav 형식
            let audioFile = command.replacingOccurrences(of: "play:", with: "")
            DispatchQueue.main.async {
                playAudio(filename: audioFile)
            }
        }.resume()
    }
    
    func playFromURL() {
        playAudio(filename: "speaker_2.wav")
    }
    
    func playAudio(filename: String) {
        // HTTP에서 오디오 다운로드 후 재생
        guard let url = URL(string: "http://192.168.219.121:8800/\(filename)") else {
            status = "❌ URL 오류"
            return
        }
        
        status = "⏳ 다운로드 중..."
        
        URLSession.shared.dataTask(with: url) { data, response, error in
            guard let data = data else {
                DispatchQueue.main.async {
                    status = "❌ 다운로드 실패"
                }
                return
            }
            
            DispatchQueue.main.async {
                do {
                    // 임시 파일로 저장
                    let tempURL = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
                    try data.write(to: tempURL)
                    
                    // 오디오 재생
                    player = try AVAudioPlayer(contentsOf: tempURL)
                    player?.play()
                    
                    status = "🔊 재생 중: \(filename)"
                } catch {
                    status = "❌ 재생 실패: \(error)"
                }
            }
        }.resume()
    }
}
