cask "sony-open-pmca" do
  version "1.0.0"
  sha256 "a042f55f9e32f8b6d05d69c501c70bdbf99f35c40735d00fb633520961913f87"

  url "https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v#{version}/Sony-Open-PMCA-#{version}-macos-arm64.zip"
  name "Sony Open PMCA"
  desc "GUI application to manage apps on Sony Alpha cameras"
  homepage "https://github.com/OpenPMCA/Sony-Open-PMCA"

  depends_on arch: :arm64
  depends_on macos: :golden_gate

  app "Sony Open PMCA.app"

  zap trash: [
    "~/Library/Saved Application State/org.openpmca.sonyopenpmca.savedState",
  ]
end
