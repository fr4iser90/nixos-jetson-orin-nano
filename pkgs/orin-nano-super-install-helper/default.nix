{ lib
, stdenvNoCC
, makeWrapper
, bash
, coreutils
, openssl
, util-linux
, parted
, dosfstools
, e2fsprogs
,
}:

let
  templates = ../../templates/orin-nano-super;
  installScript = ../../scripts/install-orin-nano-super.sh;
  prepareScript = ../../scripts/prepare-orin-nano-super-disk.sh;
  diskTools = lib.makeBinPath [
    coreutils
    bash
    util-linux
    parted
    dosfstools
    e2fsprogs
  ];
in
stdenvNoCC.mkDerivation {
  pname = "orin-nano-super-install-helper";
  version = "0.1";

  dontUnpack = true;

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    mkdir -p $out/share/orin-nano-super
    cp -Lr ${templates}/* $out/share/orin-nano-super/
    install -Dm755 ${installScript} $out/libexec/install-orin-nano-super.sh
    install -Dm755 ${prepareScript} $out/libexec/prepare-orin-nano-super-disk.sh
    makeWrapper $out/libexec/install-orin-nano-super.sh $out/bin/install-orin-nano-super \
      --set TEMPLATES_DIR $out/share/orin-nano-super \
      --prefix PATH : ${lib.makeBinPath [
        coreutils
        bash
        openssl
      ]}
    makeWrapper $out/libexec/prepare-orin-nano-super-disk.sh $out/bin/prepare-orin-nano-super-disk \
      --prefix PATH : ${diskTools}
  '';
}
