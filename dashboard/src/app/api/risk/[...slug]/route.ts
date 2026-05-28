const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? "http://darkflow_api:8000";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ slug: string[] }> }
) {
  const { slug } = await params;
  const path = slug.join("/");
  const url = new URL(request.url);
  const target = `${BACKEND}/api/risk/${path}${url.search}`;

  try {
    const res = await fetch(target);
    const data = await res.json();
    return Response.json(data);
  } catch (err) {
    return Response.json({ error: "Backend offline" }, { status: 502 });
  }
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ slug: string[] }> }
) {
  const { slug } = await params;
  const path = slug.join("/");
  const target = `${BACKEND}/api/risk/${path}`;
  const body = await request.json();

  try {
    const res = await fetch(target, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return Response.json(data);
  } catch (err) {
    return Response.json({ error: "Backend offline" }, { status: 502 });
  }
}
