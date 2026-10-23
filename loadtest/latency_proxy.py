"""A TCP proxy that adds network latency in front of a LOCAL Postgres.

Locally the database is on the same machine, so opening a connection costs
~3 ms and the app looks fast. Production talks to Neon over the internet with
TLS, where each new connection costs several round trips plus Neon's proxy,
and each query costs at least one round trip. This proxy simulates that cost so
a bottleneck that only exists in production can be reproduced and
fixed on a laptop, before spending staging time on it.

    python loadtest/latency_proxy.py --listen 15433 --upstream 127.0.0.1:5432 \\
        --connect-ms 40 --rtt-ms 10

Then point the app's DATABASE_URL at port 15433.

The numbers are a *simulation*: use them to compare before/after locally, but
quote only staging/production measurements on a CV. Defaults are deliberately
moderate. Measure the real values from production with the
zunoot_db_connect_duration_seconds and zunoot_db_query_duration_seconds metrics.
"""

import argparse
import asyncio


async def pipe(reader, writer, one_way_s):
    try:
        while data := await reader.read(65536):
            if one_way_s:
                await asyncio.sleep(one_way_s)
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        pass
    finally:
        writer.close()


async def handle(client_reader, client_writer, upstream, connect_s, one_way_s):
    # Connection set-up cost: TCP + TLS + auth handshakes, plus the cloud proxy.
    await asyncio.sleep(connect_s)
    host, port = upstream
    server_reader, server_writer = await asyncio.open_connection(host, port)
    await asyncio.gather(
        pipe(client_reader, server_writer, one_way_s),
        pipe(server_reader, client_writer, one_way_s),
    )


async def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--listen", type=int, default=15433)
    ap.add_argument("--upstream", default="127.0.0.1:5432")
    ap.add_argument("--connect-ms", type=float, default=40.0, help="extra delay when a connection is opened")
    ap.add_argument("--rtt-ms", type=float, default=10.0, help="round-trip time added to every exchange")
    args = ap.parse_args()
    host, port = args.upstream.rsplit(":", 1)
    upstream = (host, int(port))
    server = await asyncio.start_server(
        lambda r, w: handle(r, w, upstream, args.connect_ms / 1000, args.rtt_ms / 2000),
        "127.0.0.1", args.listen)
    print(f"latency proxy :{args.listen} -> {args.upstream} "
          f"(+{args.connect_ms} ms per connection, +{args.rtt_ms} ms RTT)", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
