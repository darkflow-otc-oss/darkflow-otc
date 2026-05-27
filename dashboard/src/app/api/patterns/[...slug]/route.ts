const BACKEND = process.env.NEXT_PUBLIC_API_URL ?? "http://darkflow_api:8000";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ slug: string[] }> }
) {
  const { slug } = await params;
  const path = slug.join("/");

  const url = new URL(request.url);
  const target = `${BACKEND}/api/patterns/${path}${url.search}`;

  try {
    const res = await fetch(target, {
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) {
      return Response.json(
        { error: `Backend returned ${res.status}`, data: null },
        { status: res.status }
      );
    }
    const data = await res.json();
    return Response.json(data);
  } catch {
    return Response.json(
      { error: "Backend offline", data: null },
      { status: 502 }
    );
  }
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ slug: string[] }> }
) {
  const { slug } = await params;
  const path = slug.join("/");
  const body = await request.text();

  const target = `${BACKEND}/api/patterns/${path}`;

  try {
    const res = await fetch(target, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body || undefined,
    });
    const data = await res.json();
    return Response.json(data, { status: res.status });
  } catch {
    return Response.json(
      { error: "Backend offline", data: null },
      { status: 502 }
    );
  }
}
