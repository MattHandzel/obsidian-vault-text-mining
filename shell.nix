{ pkgs ? import <nixpkgs> {} }:

let
  pythonEnv = pkgs.python312.withPackages (ps: [
    ps.pyyaml
    ps.typer
    ps.rich
    ps.requests
    ps.tqdm
    ps."python-frontmatter"
    ps.numpy
  ]);
in
pkgs.mkShell {
  packages = [ pythonEnv pkgs.git pkgs.jq pkgs.curl ];

  shellHook = ''
    echo "▶ Using Python: $(python --version)"
    export PYTHONPATH="$PWD"
  '';
}
