class Noetl < Formula
  desc "NoETL workflow automation CLI - Execute playbooks locally or orchestrate distributed pipelines"
  homepage "https://noetl.io"
  url "https://github.com/noetl/noetl/archive/refs/tags/v2.5.4.tar.gz"
  sha256 "6929fe568bf6b501c40b4558067bae4352ccad060f90533cec2b4312d4ad15ff"
  license "MIT"
  head "https://github.com/noetl/noetl.git", branch: "master"

  depends_on "rust" => :build

  def install
    cd "crates/noetlctl" do
      system "cargo", "install", *std_cargo_args
    end
  end

  test do
    assert_match "noetl", shell_output("#{bin}/noetl --version")
    
    # Test local playbook execution
    (testpath/"test.yaml").write <<~EOS
      apiVersion: noetl.io/v2
      kind: Playbook
      metadata:
        name: test
      workflow:
        - step: start
          tool:
            kind: shell
            cmds:
              - "echo 'Hello from NoETL'"
          next:
            - step: end
        - step: end
    EOS
    
    assert_match "Hello from NoETL", shell_output("#{bin}/noetl run #{testpath}/test.yaml 2>&1")
  end
end
