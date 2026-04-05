import { MongoClient, Db } from 'mongodb';

let client: MongoClient | null = null;

function getDbName(): string {
  const base = process.env.MONGO_DB_NAME || 'skku_notices';
  const env = process.env.NODE_ENV;
  if (env === 'development' || env === 'test') {
    const suffix = env === 'test' ? '_test' : '_dev';
    return `${base}${suffix}`;
  }
  return base;
}

export async function getClient(): Promise<MongoClient> {
  if (!client) {
    const url = process.env.MONGO_URL;
    if (!url) throw new Error('MONGO_URL is not set');
    client = new MongoClient(url, {
      maxPoolSize: 5,
      minPoolSize: 1,
    });
    await client.connect();
  }
  return client;
}

export async function getDb(): Promise<Db> {
  const c = await getClient();
  return c.db(getDbName());
}

export async function closeClient(): Promise<void> {
  if (client) {
    await client.close();
    client = null;
  }
}
