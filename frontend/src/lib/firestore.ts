import { getApps, initializeApp, FirebaseApp } from "firebase/app";
import {
  collection,
  Firestore,
  getDocs,
  getFirestore,
  onSnapshot,
  orderBy,
  query,
  Unsubscribe,
} from "firebase/firestore";
import { APP_CONFIG } from "./config";
import type { TickData } from "./api";

let cachedDb: Firestore | null = null;

/**
 * Initialize Firebase app and explicitly select the named Firestore database `shadow-city`
 * per docs/CONTRACT.md section 5 (`getFirestore(app, "shadow-city")`).
 */
export function getShadowCityFirestore(): Firestore {
  if (cachedDb) return cachedDb;

  const existing = getApps();
  const app: FirebaseApp =
    existing.length > 0
      ? existing[0]
      : initializeApp({
          projectId: APP_CONFIG.gcpProjectId,
          ...(APP_CONFIG.firebaseApiKey ? { apiKey: APP_CONFIG.firebaseApiKey } : {}),
          ...(APP_CONFIG.firebaseAppId ? { appId: APP_CONFIG.firebaseAppId } : {}),
        });

  cachedDb = getFirestore(app, APP_CONFIG.firestoreDatabase);
  return cachedDb;
}

/**
 * Query `scenarios/{scenarioId}/ticks` from the named Firestore database `shadow-city`.
 */
export async function fetchTicksViaFirestoreSdk(scenarioId: string): Promise<TickData[]> {
  const db = getShadowCityFirestore();
  const ticksCol = collection(db, "scenarios", scenarioId, "ticks");
  const q = query(ticksCol, orderBy("tick", "asc"));
  const snap = await getDocs(q);
  const ticks: TickData[] = [];
  snap.forEach((docSnap) => {
    const d = docSnap.data();
    ticks.push({
      scenario_id: String(d.scenario_id || scenarioId),
      tick: Number(d.tick ?? 0),
      persona_ids: Array.isArray(d.persona_ids) ? d.persona_ids : [],
      lat: Array.isArray(d.lat) ? d.lat : [],
      lng: Array.isArray(d.lng) ? d.lng : [],
      mode: Array.isArray(d.mode) ? d.mode : [],
      status: Array.isArray(d.status) ? d.status : [],
    });
  });
  return ticks;
}

/**
 * Subscribe in real time to `scenarios/{scenarioId}/ticks` on database `shadow-city`.
 */
export function subscribeScenarioTicks(
  scenarioId: string,
  onTicks: (ticks: TickData[]) => void,
  onError?: (err: Error) => void
): Unsubscribe {
  const db = getShadowCityFirestore();
  const ticksCol = collection(db, "scenarios", scenarioId, "ticks");
  const q = query(ticksCol, orderBy("tick", "asc"));
  return onSnapshot(
    q,
    (snap) => {
      const ticks: TickData[] = [];
      snap.forEach((docSnap) => {
        const d = docSnap.data();
        ticks.push({
          scenario_id: String(d.scenario_id || scenarioId),
          tick: Number(d.tick ?? 0),
          persona_ids: Array.isArray(d.persona_ids) ? d.persona_ids : [],
          lat: Array.isArray(d.lat) ? d.lat : [],
          lng: Array.isArray(d.lng) ? d.lng : [],
          mode: Array.isArray(d.mode) ? d.mode : [],
          status: Array.isArray(d.status) ? d.status : [],
        });
      });
      onTicks(ticks);
    },
    (err) => {
      if (onError) onError(err);
    }
  );
}
