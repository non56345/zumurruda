// سكربت إنشاء الفهارس لقاعدة zumurruda في mongosh
// يطابق قسم 4.2 من خطة الترحيل

const dbName = "zumurruda";
const d = db.getSiblingDB(dbName);

// 1. users: username unique
d.users.createIndex({ username: 1 }, { unique: true });

// 2. sessions: token_hash unique + TTL
d.sessions.createIndex({ token_hash: 1 }, { unique: true });
d.sessions.createIndex({ last_seen_dt: 1 }, { expireAfterSeconds: 1800 + 60 });
d.sessions.createIndex({ created_dt: 1 }, { expireAfterSeconds: 28800 + 60 });

// 3. login_attempts: key unique + TTL
d.login_attempts.createIndex({ key: 1 }, { unique: true });
d.login_attempts.createIndex({ expires_dt: 1 }, { expireAfterSeconds: 0 });

// 4. auth_events: ts + TTL 90 days
d.auth_events.createIndex({ ts: 1 });
d.auth_events.createIndex({ ts_dt: 1 }, { expireAfterSeconds: 90 * 86400 });

// 5. audit_log: rev
d.audit_log.createIndex({ rev: 1 });

// 6. gift_orders: id unique, created_at, compound ip_hash + created_at
d.gift_orders.createIndex({ id: 1 }, { unique: true });
d.gift_orders.createIndex({ created_at: 1 });
d.gift_orders.createIndex({ ip_hash: 1, created_at: 1 });

print("Indexes created successfully for database: " + dbName);
