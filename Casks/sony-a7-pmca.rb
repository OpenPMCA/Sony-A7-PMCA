cask "sony-a7-pmca" do
  version "1.0.0"
  sha256 "5c06c399066dafdd6e566b3b258d02f1434e30d3f4934d4f27fd1bf43beec433"

  url "https://github.com/OpenPMCA/Sony-A7-PMCA/releases/download/v#{version}/Sony-A7-PMCA-#{version}-macos-arm64.zip"
  name "Sony A7 PMCA"
  desc "GUI application to manage apps on Sony Alpha cameras"
  homepage "https://github.com/OpenPMCA/Sony-A7-PMCA"

  depends_on arch: :arm64
  depends_on macos: :golden_gate

  app "Sony A7 PMCA.app"

  zap trash: [
    "~/Library/Saved Application State/org.openpmca.sonya7pmca.savedState",
  ]
end
