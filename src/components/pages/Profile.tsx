import React, { useEffect, useRef, useState } from 'react';
import { useLocalProfile } from '@/hooks/useLocalProfile';
import { useLocalProfileStore } from '@/stores/localProfileStore';
import './Profile.css';

const controlCharacters = /[\u0000-\u001f\u007f-\u009f]/u;

export function profileInitials(displayName: string): string {
  return displayName.trim().split(/\s+/u).slice(0, 2).map((part) => Array.from(part)[0] ?? '').join('').toLocaleUpperCase();
}

export const Profile: React.FC = () => {
  const profile = useLocalProfileStore((state) => state.profile);
  const status = useLocalProfileStore((state) => state.status);
  const serverError = useLocalProfileStore((state) => state.error);
  const { refresh, save } = useLocalProfile();
  const [editing, setEditing] = useState(false);
  const [displayName, setDisplayName] = useState('');
  const [bio, setBio] = useState('');
  const [validation, setValidation] = useState<string | null>(null);
  const displayNameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!editing && profile !== null) {
      setDisplayName(profile.displayName);
      setBio(profile.bio ?? '');
    }
  }, [editing, profile]);

  const startEditing = () => {
    setDisplayName(profile?.displayName ?? '');
    setBio(profile?.bio ?? '');
    setValidation(null);
    setEditing(true);
    queueMicrotask(() => displayNameRef.current?.focus());
  };

  const cancelEditing = () => {
    setEditing(false);
    setValidation(null);
    setDisplayName(profile?.displayName ?? '');
    setBio(profile?.bio ?? '');
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const nextName = displayName.trim();
    const nextBio = bio.trim();
    if (!nextName || nextName.length > 80 || controlCharacters.test(nextName)) {
      setValidation('Display name must be 1–80 characters without control characters.');
      displayNameRef.current?.focus();
      return;
    }
    if (nextBio.length > 280 || controlCharacters.test(nextBio)) {
      setValidation('Bio must be at most 280 characters without control characters.');
      return;
    }
    setValidation(null);
    try {
      await save({ displayName: nextName, bio: nextBio || null });
      setEditing(false);
    } catch {
      // The hook retains the last confirmed profile; component state retains this draft.
    }
  };

  const loading = status === 'loading';
  const saving = status === 'saving';
  const unconfigured = profile === null && status === 'unconfigured';
  const loadFailed = profile === null && status === 'error';

  return (
    <div className="profile-page">
      <div className="profile-shell">
        <header className="profile-heading">
          <div><p className="profile-eyebrow">LOCAL IDENTITY</p><h1>Profile</h1><p>Personalize this device without creating an online account.</p></div>
          {profile !== null && !editing && <button type="button" className="profile-secondary" onClick={startEditing}>Edit profile</button>}
        </header>

        {(status === 'idle' || loadFailed) && <section className="profile-state" role={loadFailed ? 'alert' : 'status'}>
          <h2>{loadFailed ? 'Profile unavailable' : 'Load your local profile'}</h2>
          <p>{loadFailed ? serverError : 'The local runtime has not loaded this device profile yet.'}</p>
          <button type="button" className="profile-primary" onClick={() => void refresh().catch(() => undefined)}>Retry loading</button>
        </section>}

        {loading && <section className="profile-card profile-loading" role="status" aria-live="polite"><span className="profile-avatar profile-avatar--skeleton" /><div><span /><span /></div><p className="sr-only">Loading local profile…</p></section>}

        {unconfigured && !editing && <section className="profile-state">
          <span className="profile-avatar" aria-hidden="true">?</span>
          <h2>No local profile yet</h2>
          <p>Choose a display name for this device. Nothing is uploaded.</p>
          <button type="button" className="profile-primary" onClick={startEditing}>Create local profile</button>
        </section>}

        {profile !== null && !editing && <section className="profile-card" aria-label="Local profile">
          <span className="profile-avatar" aria-hidden="true">{profileInitials(profile.displayName)}</span>
          <div className="profile-copy"><h2>{profile.displayName}</h2><p>{profile.bio ?? 'No bio added.'}</p><small>Stored only on this device</small></div>
        </section>}

        {editing && <form className="profile-form" onSubmit={(event) => void submit(event)} aria-busy={saving}>
          <div className="profile-form-avatar" aria-hidden="true">{displayName.trim() ? profileInitials(displayName) : '?'}</div>
          <div className="profile-field"><label htmlFor="local-profile-name">Display name</label><input ref={displayNameRef} id="local-profile-name" value={displayName} maxLength={80} onChange={(event) => setDisplayName(event.target.value)} aria-describedby={validation ? 'profile-validation' : 'profile-name-help'} disabled={saving} /><small id="profile-name-help">Shown only inside this Argus installation.</small></div>
          <div className="profile-field"><label htmlFor="local-profile-bio">Bio <span>optional</span></label><textarea id="local-profile-bio" value={bio} maxLength={280} rows={4} onChange={(event) => setBio(event.target.value)} disabled={saving} /><small>{bio.length}/280</small></div>
          {validation !== null && <p id="profile-validation" className="profile-error" role="alert">{validation}</p>}
          {status === 'error' && serverError !== null && <p className="profile-error" role="alert">{serverError}</p>}
          <div className="profile-actions"><button type="button" className="profile-secondary" onClick={cancelEditing} disabled={saving}>Cancel</button><button type="submit" className="profile-primary" disabled={saving}>{saving ? 'Saving…' : profile === null ? 'Create profile' : 'Save changes'}</button></div>
        </form>}
      </div>
    </div>
  );
};
