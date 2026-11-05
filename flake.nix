{
  description = "lazytwister - lazygit-style TUI for Zephyr twister tests";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" "x86_64-darwin" ];
      forAll = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in {
      packages = forAll (pkgs: rec {
        lazytwister = pkgs.python3Packages.buildPythonApplication {
          pname = "lazytwister";
          version = "0.1.0";
          pyproject = true;
          src = ./.;
          build-system = [ pkgs.python3Packages.setuptools ];
          dependencies = with pkgs.python3Packages; [ textual watchfiles pyyaml ];
          nativeCheckInputs = with pkgs.python3Packages; [ pytestCheckHook pytest-asyncio ];
        };
        default = lazytwister;
      });

      devShells = forAll (pkgs: {
        default = pkgs.mkShell {
          packages = [
            (pkgs.python3.withPackages (ps: with ps; [
              textual watchfiles pyyaml pytest pytest-asyncio
            ]))
          ];
        };
      });
    };
}
