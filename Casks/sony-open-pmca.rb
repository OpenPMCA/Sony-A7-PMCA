cask "sony-open-pmca" do
  version "1.1.0"
  sha256 "395ec2bb352f863692b6322b9a52b93061eedcbea19877ff03c46da9552ecf3c"

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
