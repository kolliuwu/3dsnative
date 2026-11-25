import SwiftUI

// Placeholder shell. No game code yet: the loader, CPU, OS and GPU layers
// are planned in docs/PLAN.md and are not implemented.
struct ContentView: View {
    var body: some View {
        VStack(spacing: 12) {
            Text("N3DS Native")
                .font(.title)
            Text("Shell only. No games run yet.")
                .foregroundStyle(.secondary)
        }
        .padding()
    }
}
