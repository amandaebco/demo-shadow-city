export const APP_CONFIG = {
  gcpProjectId: process.env.NEXT_PUBLIC_GCP_PROJECT_ID || "ebc-cloud-dev-03",
  firestoreDatabase: process.env.NEXT_PUBLIC_FIRESTORE_DATABASE || "shadow-city",
  firebaseApiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY || "",
  firebaseAppId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID || "",
  orchestratorUrl: (
    process.env.NEXT_PUBLIC_ORCHESTRATOR_URL ||
    "https://orchestrator-697653429683.asia-southeast2.run.app"
  ).replace(/\/$/, ""),
  googleMapsApiKey: process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY || "",
  defaultScenarioId: "s_central_parking_100_with_north_jakarta_t_78f06b",
  jakartaCenter: {
    lat: -6.172,
    lng: 106.845,
    zoom: 11.35,
  },
} as const;
