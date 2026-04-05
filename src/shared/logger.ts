import pino from 'pino';

const level = process.env.NODE_ENV === 'test' ? 'silent' : 'info';

const logger = pino({
  level,
  ...(process.env.NODE_ENV === 'development' && {
    transport: { target: 'pino-pretty' },
  }),
});

export default logger;
