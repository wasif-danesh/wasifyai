"""Rules every UserStore must follow (ADR-0030); run against memory and Postgres."""

from wasifyai_api.auth import Claims

NO_ADMINS: frozenset[str] = frozenset()


def claims(
    provider="google",
    account="a1",
    email: str | None = "ann@example.com",
    verified=True,
    name="Ann",
) -> Claims:
    return Claims(provider, account, email, verified, name, None)


async def check_contract(store, tenant: str) -> None:
    # the same provider account is always the same user
    first = await store.resolve(tenant, claims(), NO_ADMINS)
    again = await store.resolve(tenant, claims(name="Ann B"), NO_ADMINS)
    assert first.id == again.id and first.role == "user"

    # a second provider with the same verified email joins the user
    gh = await store.resolve(tenant, claims("github", "g1", "ANN@example.com"), NO_ADMINS)
    assert gh.id == first.id

    # an unverified email never links, even when it matches
    unverified = await store.resolve(
        tenant, claims("microsoft-entra-id", "m1", "ann@example.com", verified=False), NO_ADMINS
    )
    assert unverified.id != first.id

    # nor does a verified identity link to a user whose email is unverified
    other = await store.resolve(tenant, claims("google", "a2", "ann@example.com"), NO_ADMINS)
    assert other.id == first.id  # verified and equal: links to the verified user, not the other

    # no email at all: a user of its own
    anon = await store.resolve(tenant, claims("github", "g2", None, verified=False), NO_ADMINS)
    assert anon.id not in {first.id, unverified.id}

    # tenants are separate
    elsewhere = await store.resolve(tenant + "-b", claims(), NO_ADMINS)
    assert elsewhere.id != first.id

    # admin comes only from a verified email on the list, and stays once granted
    admins = frozenset({"boss@example.com"})
    not_verified = await store.resolve(
        tenant, claims("github", "b1", "boss@example.com", verified=False), admins
    )
    assert not_verified.role == "user"
    boss = await store.resolve(tenant, claims("google", "b2", "Boss@Example.com"), admins)
    assert boss.role == "admin"
    assert (
        await store.resolve(tenant, claims("google", "b2", "boss@example.com"), NO_ADMINS)
    ).role == "admin"
