# Orin Nano (and similar) kernels may expose fbp_pg_mask as read-only or reject
# writes with ENODEV. Official nvpmodel_*.conf files still reference FBP_POWER_GATING,
# which makes nvpmodel exit 255. This derivation strips those lines from a chosen conf.
{ lib
, runCommand
, l4t-nvpmodel
, confName ? "nvpmodel_p3767_0003_super.conf"
}:

runCommand "nvpmodel-without-fbp-${lib.removeSuffix ".conf" confName}"
  {
    preferLocalBuild = true;
    allowSubstitutes = false;
  }
  ''
    mkdir -p "$out"
    sed \
      -e '/FBP_POWER_GATING/d' \
      -e '/FBP_PG/d' \
      "${l4t-nvpmodel}/etc/nvpmodel/${confName}" > "$out/nvpmodel.conf"
  ''
