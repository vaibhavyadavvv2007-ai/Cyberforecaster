"""Live traffic monitoring — the demo-day capability.

Packets on the network interface → the SAME 18 window features the model was
trained on → the SAME trained forecaster → a live forecast, in front of the
jury, while a teammate attacks the demo network from a second device.

Modules:
- packet_windower  packets → per-bin window features (mirrors window_builder)
- sensor           scapy/Npcap capture thread feeding the windower
- history          seeded + live window buffer, forecaster calls, events

Honesty contract for this module (say it to the jury, don't hide it):
- The training features come from CICFlowMeter flow records; live features are
  computed from raw packets by THIS module. They are semantically the same
  aggregates (same names, same definitions to the extent packets allow), but
  not bit-identical to CICFlowMeter output. The scaler was fitted on training
  distributions, so live traffic is by definition closer to the training
  distribution than any synthetic input — but a live attack is still
  out-of-distribution until rehearsed. That is why scripts/live_rehearsal.py
  exists: verify detection BEFORE demo day, never tune on stage.
"""
