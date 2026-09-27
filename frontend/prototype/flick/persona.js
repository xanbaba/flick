// Fixture data for the in-browser mock backend only. The real backend owns all of this
// (data/fixtures/persona_marcus.json, config.yaml). Nothing here is presented as measured data.

export const PERSONA_NAME = 'Marcus Alvarez';
export const PERSONA_BIO = 'Marcus Alvarez, 54, a former high-school music teacher in Miami. Diagnosed with ALS three years ago; he now has no reliable speech or hand movement. His daughter Sofia visits on Sunday afternoons and he calls her "mija". His grandson Mateo is four. His wife Elena manages his care. His home nurse is Priya, who comes on weekday mornings. He has a nine-year-old beagle called Rosie who sleeps under his chair. He hates the living-room recliner because it hurts his lower back, and prefers the window seat where he can see the jacaranda tree. He used to play trumpet in a salsa band called Los Vientos. He is stubborn about not being spoken over, likes his coffee unreasonably strong, and watches Marlins games with the sound off.';

// Mirrors config.yaml (stimulus.profiles, decision, eeg, privacy.price_table) for the mock only.
export const PROFILES = {
  hi: { frequencies: [8.0, 9.6, 11.4, 13.2, 15.0], phases: [0, 1.5707963, 3.1415927, 4.712389, 0], cancel_idx: 4, window_s: 1.25, bandpass_low_hz: 6.0 },
  lo: { frequencies: [6.667, 7.5, 8.571, 12.0, 10.0], phases: [0, 1.5707963, 3.1415927, 4.712389, 0], cancel_idx: 4, window_s: 2.0, bandpass_low_hz: 5.0 },
};
export const DECISION = { rho_threshold: 0.35, margin_ratio: 1.15, dwell_windows: 3, refractory_s: 1.0 };
export const CHANNELS = ['O1', 'Oz', 'O2', 'POz', 'PO3', 'PO4', 'Pz', 'CPz'];
export const PRICE = { gemini_in_per_1k: 0.000075, gemini_out_per_1k: 0.0003, elevenlabs_per_1k_chars: 0.30, deepgram_per_minute: 0.0043 };

const K = { P: 'Person', L: 'Place', T: 'Thing', A: 'Activity', N: 'Need', M: 'Memory' };

// id|kind|label|weight|edges   edges: REL>target (this→target) or REL<source (source→this)
const SEED = `
user|P|Marcus Alvarez|5|
sofia|P|Sofia|3|KNOWS<user LIKES<user
elena|P|Elena|3|KNOWS<user LIKES<user
mateo|P|Mateo|2.6|KNOWS<user KNOWS<sofia
priya|P|Priya|2.4|KNOWS<user KNOWS<elena
miami|L|Miami|2|LOCATED_AT<user
home|L|Home|2.2|LOCATED_AT<user LOCATED_AT<elena
living_room|L|Living room|1.6|LOCATED_AT<user
window_seat|L|Window seat|2.4|LIKES<user
high_school|L|High school|1.4|
little_havana|L|Little Havana|1|
ballpark|L|loanDepot park|0.9|
kitchen|L|Kitchen|1|
bedroom|L|Bedroom|1|
front_yard|L|Front yard|1|
clinic|L|ALS clinic|1.2|
sofia_home|L|Sofia's apartment|0.8|LOCATED_AT<sofia
recliner|T|Living-room recliner|2|DISLIKES<user LOCATED_AT>living_room
jacaranda|T|Jacaranda tree|2.2|LIKES<user LOCATED_AT>front_yard
rosie|T|Rosie the beagle|2.4|LIKES<user LIKES<mateo
his_chair|T|His chair|1.4|LOCATED_AT>living_room RELATES_TO<rosie
trumpet|T|Trumpet|2.2|LIKES<user
coffee|T|Strong coffee|2|LIKES<user
tv|T|TV|1.2|LOCATED_AT>living_room
wheelchair|T|Power wheelchair|1.4|NEEDS<user
hospital_bed|T|Hospital bed|1.1|LOCATED_AT>bedroom
lift|T|Patient lift|1|LOCATED_AT>bedroom
bipap|T|BiPAP mask|1.1|LOCATED_AT>bedroom
records|T|Salsa records|1.2|LIKES<user
sheet_music|T|Sheet music|0.9|RELATES_TO<trumpet
band_photos|T|Band photo album|1|RELATES_TO>trumpet
marlins_cap|T|Marlins cap|0.9|LIKES<user
remote|T|TV remote|0.8|RELATES_TO<tv
leash|T|Rosie's leash|0.8|RELATES_TO<rosie
dog_food|T|Rosie's food|0.8|RELATES_TO<rosie
cafetera|T|Stovetop espresso pot|1|RELATES_TO<coffee LOCATED_AT>kitchen
cup|T|Coffee cup with a straw|0.9|RELATES_TO<coffee
picture_books|T|Picture books|0.9|LIKES<mateo
blocks|T|Building blocks|0.8|LIKES<mateo
family_photos|T|Family photos|1|LOCATED_AT>living_room
pill_organizer|T|Pill organizer|0.9|LOCATED_AT>kitchen
bp_cuff|T|Blood pressure cuff|0.8|RELATES_TO>vitals
blanket|T|Window-seat blanket|0.9|LOCATED_AT>window_seat
radio|T|Kitchen radio|0.8|LOCATED_AT>kitchen
headset|T|EEG headset|1.3|NEEDS<user
sunday_visit|A|Sunday afternoon visits|2.2|DOES<sofia LIKES<user
morning_care|A|Weekday morning care|2|DOES<priya
salsa|A|Trumpet in Los Vientos|2.2|DOES<user
teaching|A|Teaching high-school music|1.8|DOES<user LOCATED_AT>high_school
marlins|A|Marlins games, sound off|2|DOES<user LOCATED_AT>living_room
coffee_time|A|Morning coffee|1.6|DOES<user
stretches|A|Stretching routine|1.2|DOES<priya
dog_walk|A|Walking Rosie|1|DOES<elena
story_time|A|Story time with Mateo|1.1|DOES<user DOES<mateo
care_plan|A|Managing his care|1.6|DOES<elena
jacaranda_watch|A|Watching the jacaranda|1.4|DOES<user LOCATED_AT>window_seat
listening|A|Listening to salsa|1.2|DOES<user
clinic_visits|A|Clinic appointments|1|LOCATED_AT>clinic DOES<elena
vitals|A|Morning vitals check|0.9|DOES<priya
shower|A|Shower assistance|0.8|DOES<priya
rehearsal|A|Band rehearsals|0.9|RELATES_TO<salsa
gigs|A|Weekend gigs|1|RELATES_TO<salsa LOCATED_AT>little_havana
game_nights|A|Game nights with Elena|1|RELATES_TO<marlins DOES<elena
phone_calls|A|Phone calls with Sofia|0.8|DOES<sofia
ballgames|A|Going to the ballpark|0.8|LOCATED_AT>ballpark RELATES_TO<marlins
back_support|N|Lower-back support|2|NEEDS<user RELATES_TO>recliner
not_spoken_over|N|Not being spoken over|2|NEEDS<user
transfers|N|Help with transfers|1.4|NEEDS<user RELATES_TO>lift
communication|N|A way to speak|1.8|NEEDS<user RELATES_TO>headset
breathing|N|Breathing support at night|1.2|NEEDS<user RELATES_TO>bipap
repositioning|N|Regular repositioning|1|NEEDS<user RELATES_TO>hospital_bed
hydration|N|Hydration|0.9|NEEDS<user RELATES_TO>cup
m_als|M|Diagnosed with ALS three years ago|1.8|INVOLVES>user INVOLVES>clinic
m_band|M|Played trumpet in the salsa band Los Vientos|1.8|INVOLVES>trumpet INVOLVES>salsa
m_teacher|M|Taught music at a Miami high school|1.5|INVOLVES>teaching INVOLVES>high_school
m_mija|M|Calls his daughter Sofia "mija"|1.6|INVOLVES>sofia
m_mateo|M|Grandson Mateo is four|1.2|INVOLVES>mateo
m_rosie|M|Rosie sleeps under his chair|1.3|INVOLVES>rosie INVOLVES>his_chair
m_recliner|M|The recliner hurts his lower back|1.5|INVOLVES>recliner INVOLVES>back_support
m_window|M|Prefers the window seat to see the jacaranda|1.5|INVOLVES>window_seat INVOLVES>jacaranda
m_coffee|M|Likes his coffee unreasonably strong|1.3|INVOLVES>coffee
m_marlins|M|Watches Marlins games with the sound off|1.3|INVOLVES>marlins INVOLVES>tv
m_stubborn|M|Stubborn about not being spoken over|1.4|INVOLVES>not_spoken_over INVOLVES>user
m_priya|M|Priya comes on weekday mornings|1.1|INVOLVES>priya INVOLVES>morning_care
m_elena|M|Elena manages his care|1.1|INVOLVES>elena INVOLVES>care_plan
m_sunday|M|Sofia visits on Sunday afternoons|1.2|INVOLVES>sofia INVOLVES>sunday_visit
m_speech|M|Lost reliable speech and hand movement|1.2|INVOLVES>communication INVOLVES>user
m_gigs|M|Weekend gigs with Los Vientos in Little Havana|0.9|INVOLVES>gigs INVOLVES>little_havana
m_students|M|Former students still stop by|0.8|INVOLVES>teaching
m_bloom|M|The jacaranda turns purple in spring|0.9|INVOLVES>jacaranda
m_yard|M|Mateo and Rosie play in the front yard|0.8|INVOLVES>mateo INVOLVES>rosie INVOLVES>front_yard
m_records|M|Keeps his old salsa records by the TV|0.8|INVOLVES>records INVOLVES>tv
m_cap|M|Wears his Marlins cap on game nights|0.8|INVOLVES>marlins_cap INVOLVES>game_nights
`;

export function buildSeed() {
  const nodes = [], edges = [], now = Date.now() / 1000;
  for (const line of SEED.trim().split('\n')) {
    const [id, k, label, w, rels] = line.split('|');
    nodes.push({ id, label, kind: K[k], weight: +w, last_accessed: now });
    for (const r of (rels || '').split(' ').filter(Boolean)) {
      const out = r.includes('>');
      const [rel, other] = r.split(out ? '>' : '<');
      const source = out ? id : other, target = out ? other : id;
      edges.push({ id: `${source}-${rel}-${target}`, source, target, kind: rel, weight: 1 });
    }
  }
  return { nodes, edges };
}

// Scripted turns. Each attempt is one round-2 pass; a Cancel pick (tile 4) returns to the intents.
export const TURNS = [
  {
    partner_id: 'sofia', partner_name: 'Sofia', confidence: 0.94,
    utterance: 'Hi Papi! How are you feeling today?',
    retrieve: ['sofia', 'm_mija', 'sunday_visit', 'm_sunday', 'back_support', 'recliner'],
    intents: ['Doing okay', 'Back hurts', 'Missed you mija', 'How is Mateo'],
    attempts: [{
      intent: 1,
      retrieve: ['recliner', 'm_recliner', 'back_support', 'window_seat', 'jacaranda', 'm_window'],
      candidates: ["My back's bad today.", "That recliner has been killing my lower back again.", "Honestly, mija, my back hurts. Can you help me over to the window seat so I can see the jacaranda?"],
      grounding: ['recliner', 'm_recliner', 'back_support', 'window_seat', 'jacaranda', 'm_mija'],
      pick: 2,
    }],
    voice: 'elevenlabs',
    learn: { nodes: [['lumbar_cushion', 'Thing', 'Lumbar cushion'], ['m_back_flare', 'Memory', 'Back pain flared up during a Sunday visit']], edges: [['NEEDS', 'user', 'lumbar_cushion'], ['RELATES_TO', 'back_support', 'lumbar_cushion'], ['INVOLVES', 'm_back_flare', 'sofia'], ['INVOLVES', 'm_back_flare', 'back_support']] },
  },
  {
    partner_id: 'priya', partner_name: 'Priya', confidence: 0.88,
    utterance: 'Morning Marcus! Coffee first, or should we start with your stretches?',
    retrieve: ['priya', 'morning_care', 'stretches', 'coffee', 'coffee_time', 'm_priya'],
    intents: ['Coffee first', 'Stretches first', 'Make it strong', 'Where is Rosie'],
    attempts: [{
      intent: 2,
      retrieve: ['coffee', 'm_coffee', 'cafetera', 'cup', 'coffee_time'],
      candidates: ['Coffee first, strong.', 'Coffee first please, and make it unreasonably strong.', "Morning, Priya. Coffee before anything else, and don't go easy on it. You know how I take it."],
      grounding: ['coffee', 'm_coffee', 'coffee_time', 'priya', 'morning_care'],
      pick: 1,
    }],
    voice: 'cache',
    learn: { nodes: [['m_coffee_first', 'Memory', 'Wants coffee before his morning stretches']], edges: [['INVOLVES', 'm_coffee_first', 'priya'], ['INVOLVES', 'm_coffee_first', 'coffee'], ['INVOLVES', 'm_coffee_first', 'stretches']] },
  },
  {
    partner_id: 'elena', partner_name: 'Elena', confidence: 0.91,
    utterance: 'The Marlins play at seven tonight. Want me to put the game on?',
    retrieve: ['elena', 'marlins', 'm_marlins', 'game_nights', 'tv', 'marlins_cap'],
    intents: ['Yes sound off', 'Maybe later', 'Who is pitching', 'Watch with me'],
    attempts: [
      {
        intent: 3,
        retrieve: ['elena', 'game_nights', 'window_seat'],
        candidates: ['Watch it with me.', 'Only if you watch it with me tonight.', 'Put it on and come sit with me, love. It is no fun watching alone.'],
        grounding: ['elena', 'game_nights'],
        pick: 4,
      },
      {
        intent: 0,
        retrieve: ['marlins', 'm_marlins', 'tv', 'remote', 'm_cap', 'marlins_cap'],
        candidates: ['Yes, sound off.', 'Put the game on, but keep the sound off, please.', 'Yes, love. Put the Marlins on with the sound off, and bring me my cap.'],
        grounding: ['marlins', 'm_marlins', 'tv', 'marlins_cap', 'elena'],
        pick: 2,
      },
    ],
    voice: 'elevenlabs',
    learn: { nodes: [['m_game_7', 'Memory', 'Asked for the Marlins game with the sound off']], edges: [['INVOLVES', 'm_game_7', 'elena'], ['INVOLVES', 'm_game_7', 'marlins']] },
  },
  {
    partner_id: 'mateo', partner_name: 'Mateo', confidence: 0.81,
    utterance: 'Abuelo, can you play the trumpet for me?',
    retrieve: ['mateo', 'trumpet', 'm_band', 'salsa', 'story_time'],
    intents: ['Not anymore', 'Los Vientos', 'Show you videos', 'Your turn'],
    attempts: [{
      intent: 1,
      retrieve: ['trumpet', 'salsa', 'm_band', 'band_photos', 'gigs', 'm_gigs'],
      candidates: ['I used to, in Los Vientos.', 'I played trumpet in a salsa band called Los Vientos.', "I can't play anymore, mijo, but ask your mom for the Los Vientos photos. That's me on the trumpet."],
      grounding: ['trumpet', 'salsa', 'm_band', 'band_photos', 'mateo', 'sofia'],
      pick: 2,
    }],
    voice: 'elevenlabs',
    learn: { nodes: [['m_mateo_trumpet', 'Memory', 'Mateo asked him to play the trumpet']], edges: [['LIKES', 'mateo', 'trumpet'], ['INVOLVES', 'm_mateo_trumpet', 'mateo'], ['INVOLVES', 'm_mateo_trumpet', 'trumpet']] },
  },
];

// What the offline `static` LLM provider would return for any utterance.
export const STATIC_INTENTS = ['Yes', 'No', 'Tell me more', 'Not now'];
export const STATIC_CANDIDATES = {
  Yes: ['Yes.', 'Yes, that sounds good to me.', "Yes, let's do that. Thanks for asking me."],
  No: ['No.', "No, I'd rather not right now.", "No thanks. Ask me again a bit later, okay?"],
  'Tell me more': ['Tell me more.', 'Go on, tell me more about it.', "I want to hear the rest of that. Keep going, I'm listening."],
  'Not now': ['Not now.', "Not right now, maybe later.", "Can we come back to this later? I'm not up for it right now."],
};
