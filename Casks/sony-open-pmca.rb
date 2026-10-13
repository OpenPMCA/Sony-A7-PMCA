cask "sony-open-pmca" do
  version "1.2.0"
  sha256 "ae123f7a6e56659b2b864d96d7b39b0ac48cfb252af3ce335d09f06c826e8113"

  url "https://github.com/OpenPMCA/Sony-Open-PMCA/releases/download/v#{version}/Sony-Open-PMCA-#{version}-macos-arm64.zip"
  name "Sony Open PMCA"
  desc "GUI application to manage apps on Sony Alpha cameras"
  homepage "https://github.com/OpenPMCA/Sony-Open-PMCA"

  depends_on arch: :arm64
  depends_on macos: :sonoma

  app "Sony Open PMCA.app"

  zap trash: [
    "~/Library/Saved Application State/org.openpmca.sonyopenpmca.savedState",
  ]
end
