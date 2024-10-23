{pkgs}: {
  deps = [
    pkgs.pkgconfig
    pkgs.cairo
    pkgs.gobject-introspection
    pkgs.dbus
    pkgs.bluez-tools
    pkgs.bluez
  ];
}
