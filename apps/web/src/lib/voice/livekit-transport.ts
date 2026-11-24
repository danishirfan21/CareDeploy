import {
  ParticipantKind,
  Room,
  RoomEvent,
  Track,
  type RemoteTrack,
} from "livekit-client";
import {
  MicrophoneDeniedError,
  type TransportEvent,
  type VoiceTransport,
} from "./transport";

/** Real LiveKit adapter. Holds only the short-lived participant token, never an API secret. */
export class LiveKitTransport implements VoiceTransport {
  private room = new Room({ adaptiveStream: false, dynacast: false });
  private handlers = new Set<(e: TransportEvent) => void>();
  private audio: HTMLMediaElement[] = [];

  private emit(e: TransportEvent) {
    this.handlers.forEach((h) => h(e));
  }

  subscribe(handler: (e: TransportEvent) => void) {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }

  async connect(url: string, token: string) {
    const r = this.room;
    r.on(RoomEvent.Reconnecting, () => this.emit({ type: "reconnecting" }));
    r.on(RoomEvent.Reconnected, () => this.emit({ type: "connected" }));
    r.on(RoomEvent.Disconnected, (reason) =>
      this.emit({ type: "disconnected", reason: reason?.toString() }),
    );
    r.on(RoomEvent.ParticipantConnected, (p) => {
      if (p.kind === ParticipantKind.AGENT) this.emit({ type: "agent_joined" });
    });
    r.on(RoomEvent.ParticipantDisconnected, (p) => {
      if (p.kind === ParticipantKind.AGENT) this.emit({ type: "agent_left" });
    });
    r.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
      if (track.kind === Track.Kind.Audio) {
        const el = track.attach();
        el.style.display = "none";
        document.body.appendChild(el);
        this.audio.push(el);
      }
    });
    await r.connect(url, token);
    this.emit({ type: "connected" });
    if (
      [...r.remoteParticipants.values()].some(
        (p) => p.kind === ParticipantKind.AGENT,
      )
    ) {
      this.emit({ type: "agent_joined" });
    }
    try {
      await r.localParticipant.setMicrophoneEnabled(true);
    } catch {
      await r.disconnect();
      throw new MicrophoneDeniedError();
    }
  }

  async setMicEnabled(enabled: boolean) {
    await this.room.localParticipant.setMicrophoneEnabled(enabled);
  }

  async disconnect() {
    await this.room.disconnect();
    this.audio.forEach((a) => a.remove());
    this.audio = [];
  }
}
