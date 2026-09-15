# Apple signing and notarization — activation runbook

This is the only thing that removes the macOS Gatekeeper approval entirely. It
applies to the **frozen standalone build**, not to the source-checkout wrapper.

## What is already built

`.github/workflows/desktop-build.yml` implements the whole chain: keychain
import, `codesign --force --deep --options runtime --timestamp`,
`xcrun notarytool submit --wait`, `xcrun stapler staple` + `validate`,
`spctl --assess`, the `DISTRIBUTION_SECURITY_STATUS.json` transition to
`SIGNED_NOTARIZED_STAPLED_GATEKEEPER_PASSED`, and a cleanup step that destroys the
temporary keychain and the decoded certificate.

**There is no workflow code to write.** Activation is supplying six repository
secrets. The `Require signing configuration for public macOS release` step fails
closed and names the first missing one, so a dry run is safe.

## The six secrets

| Secret | Where it comes from |
|---|---|
| `APPLE_DEVELOPER_ID_P12_BASE64` | A **Developer ID Application** certificate exported from Keychain Access *with its private key* as `.p12`, then `base64 -i cert.p12 \| pbcopy`. Not "Apple Development", not "Mac App Distribution" — those cannot notarize for distribution outside the App Store. |
| `APPLE_DEVELOPER_ID_P12_PASSWORD` | The password set during that `.p12` export. |
| `APPLE_SIGNING_IDENTITY` | The exact common name, e.g. `Developer ID Application: Jane Doe (ABCDE12345)`. Read it from `security find-identity -v -p codesigning`; a mismatch fails at `codesign`, not earlier. |
| `APPLE_ID` | The Apple ID email on the developer account. |
| `APPLE_TEAM_ID` | The 10-character Team ID from the portal's Membership page. |
| `APPLE_APP_SPECIFIC_PASSWORD` | Generated at appleid.apple.com → Sign-In and Security → App-Specific Passwords. **Not** the account password — `notarytool` rejects that. |

## Steps

1. Enrol in the Apple Developer Program ($99/yr). An Individual account is
   sufficient; a Team ID is issued either way.
2. Create the Developer ID Application certificate (Developer portal, or
   Xcode → Settings → Accounts → Manage Certificates).
3. Export it with its private key, base64 it, and set the six secrets above as
   **repository** secrets.
4. Push a `desktop-v*` tag to trigger a public release build.
5. Verify on the downloaded artifact — the workflow already captures all three as
   release evidence (`CODESIGN_VERIFY.txt`, `STAPLER_VALIDATE.txt`,
   `GATEKEEPER_ASSESS.txt`):

   ```bash
   codesign --verify --deep --strict --verbose=2 PRII-MONEYSWEEP.app
   xcrun stapler validate PRII-MONEYSWEEP.app
   spctl --assess --type execute --verbose=4 PRII-MONEYSWEEP.app
   ```

## What still blocks a public release

Secrets alone are not sufficient. `desktop-build.yml` also refuses to publish
unless `data/exports/production_status.json` reports
`production_status == PRODUCTION_VALIDATED`. It currently reports
`NON_PRODUCTION_DIAGNOSTIC` with three blockers (populated data layers 3 of 8
required, unique entities 18 of 100 required, and fixture/synthetic-data
signatures detected).

That gate is intentional and is not relaxed by this runbook: it exists so a
technically self-contained application cannot be published as a production
MoneySweep release while the bundled data is still diagnostic. Signing and data
validity are independent prerequisites and both must be met.

## Rotation

Developer ID certificates expire after five years; app-specific passwords can be
revoked at any time. Revoking either silently breaks releases until the secret is
replaced — there is no warning ahead of the next tagged build.

## Scope

This makes the **frozen release download** open with no prompt. It does not, and
cannot, make the committed source-tree `PRII-MONEYSWEEP.app` prompt-free: that
bundle's executable is a shell script that runs code from the checkout around it,
which is neither signable nor staple-able as a distributed unit. The source
checkout will always cost one Gatekeeper approval per machine; see
`desktop/README.md` for how that approval is reduced to a single step.
