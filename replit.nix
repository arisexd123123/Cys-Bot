{pkgs}: {
  deps = [
    pkgs.lsof
    pkgs.yakut
    pkgs.python311Packages.pip
    pkgs.libopus
    pkgs.ffmpeg-full
  ];
}
