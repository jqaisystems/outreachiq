# Deterministic local email/LinkedIn draft generator (no AI calls).
# PERSONALIZE BEFORE USE: replace the "{Your Name}" sign-offs and the generic
# proof sentences in the body templates below with your own name and portfolio
# proof so drafts sound like you.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$toWritePath = Join-Path $root "data\to_write.json"
$outPath = Join-Path $root "data\written.json"

function Test-Email($value) {
    if ([string]::IsNullOrWhiteSpace($value)) { return $false }
    return $value -match '^[^@\s]+\@[^@\s]+\.[^@\s]+$'
}

function Clean-Text($value) {
    if ($null -eq $value) { return "" }
    $s = [string]$value
    $s = $s -replace [char]0x2013, "-"
    $s = $s -replace [char]0x2014, "-"
    $s = $s -replace [char]0x2019, "'"
    $s = $s -replace [char]0x2018, "'"
    $s = $s -replace [char]0x201c, '"'
    $s = $s -replace [char]0x201d, '"'
    return $s.Trim()
}

function Short-Name($name) {
    $n = Clean-Text $name
    $n = $n -replace '\s+\|.*$', ''
    $n = $n -replace '\s+-\s+.*$', ''
    $n = $n -replace '\s+Powered by.*$', ''
    if ($n.Length -gt 34) { return $n.Substring(0, 34).Trim() }
    return $n
}

function Greeting($lead) {
    $dm = Clean-Text $lead.decision_maker
    if ($dm) {
        $first = ($dm -split '\s+')[0]
        if ($first) { return "Hi $first," }
    }
    $name = Clean-Text $lead.name
    if ($name -match '^([A-Z][a-z]+)\s+[A-Z][a-z]+') {
        return "Hi $($Matches[1]),"
    }
    return "Hi team,"
}

function Lead-Category($lead) {
    $text = ((Clean-Text $lead.niche) + " " + (Clean-Text $lead.industry) + " " + (Clean-Text $lead.name)).ToLowerInvariant()
    if ($text -match 'real estate|realtor|realty|homes|property') { return "real estate" }
    if ($text -match 'yacht|luxury|cars|jewelry|hotel|hospitality') { return "luxury" }
    if ($text -match 'law|legal') { return "law" }
    if ($text -match 'finance|wealth|accounting|advisor') { return "finance" }
    if ($text -match 'architect|interior|design studio') { return "architecture and interiors" }
    if ($text -match 'fitness|sports|athletic') { return "fitness" }
    return "business"
}

function City-Line($lead) {
    $city = Clean-Text $lead.city
    if ($city) { return $city }
    $country = Clean-Text $lead.country
    if ($country) { return $country }
    return "your market"
}

function Contact-Email($lead) {
    foreach ($candidate in @($lead.contact_email, $lead.contact_page_email)) {
        $email = Clean-Text $candidate
        if (Test-Email $email) { return $email }
    }
    if ($lead.contact_page_emails) {
        foreach ($candidate in $lead.contact_page_emails) {
            $email = Clean-Text $candidate
            if (Test-Email $email) { return $email }
        }
    }
    return ""
}

function Make-LinkedInProfile($lead, $greetingName) {
    $name = Clean-Text $lead.decision_maker
    $title = Clean-Text $lead.decision_maker_title
    $url = Clean-Text $lead.linkedin_url
    if (-not $name) {
        $short = Short-Name $lead.name
        $name = $short
        $title = "Owner or marketing lead"
    }
    if (-not $title) { $title = "Decision-maker" }

    $company = Short-Name $lead.name
    $city = City-Line $lead
    $category = Lead-Category $lead
    $note = "Hi $greetingName, I came across $company in $city and liked the focus you are building. I am a brand identity designer working with $category brands. Would love to connect. - {Your Name}"
    if ($note.Length -gt 300) {
        $note = "Hi $greetingName, I came across $company and liked what you are building. I am a brand identity designer. Would love to connect. - {Your Name}"
    }

    [ordered]@{
        name = $name
        title = $title
        url = $url
        connection_note = $note
        follow_up_message = "Hi $greetingName, thanks for connecting. I came across $company while looking at $category brands in $city. The work already has useful proof points, and I thought there may be room to make the brand presence feel more distinctive across the first touchpoints. Happy to share the thinking behind it. - {Your Name}"
        engagement_suggestions = @(
            "Check the company or founder LinkedIn page before connecting and like a recent post about listings, projects, client wins, or market updates.",
            "Leave a short non-sales comment on a recent post that reinforces the specific market or client segment they serve."
        )
    }
}

function Make-Draft($lead) {
    $company = Short-Name $lead.name
    $city = City-Line $lead
    $category = Lead-Category $lead
    $greeting = Greeting $lead
    $greetingName = ($greeting -replace '^Hi\s+', '' -replace ',$', '')
    if ($greetingName -eq "team") { $greetingName = "there" }
    $reviews = 0
    if ($null -ne $lead.review_count) { $reviews = [int]$lead.review_count }
    $proof = if ($reviews -gt 0) { "$reviews reviews" } else { "a visible local presence" }
    $signals = (Clean-Text $lead.brand_signals).ToLowerInvariant()
    $summary = (Clean-Text $lead.website_summary).ToLowerInvariant()

    $trigger = if (-not (Clean-Text $lead.website_summary)) {
        "$company has a visible presence in $city, but the exported enrichment did not capture a clear website story."
    } elseif ($summary -match '403 forbidden|recaptcha|exceeding|security review' -or $signals -match 'sparse|no headings') {
        "$company already has market proof, but the first website impression appears thin or technically blocked."
    } elseif ($signals -match 'luxury|premium|high-end|exclusive') {
        "$company operates in a premium $category segment where the brand can carry more perceived value."
    } else {
        "$company has market traction in $city, and the next opportunity is making that presence more ownable."
    }

    $subjectA = "Quick thought on $company"
    if ($subjectA.Length -gt 40) { $subjectA = "$company brand thought" }
    $subjectB = "A similar brand came to mind"
    $subjectC = "$category brands in $city"
    if ($subjectC.Length -gt 40) { $subjectC = "$company's edge" }

    $bodyA = "$greeting`n`nI came across $company and noticed the proof you already have in $city, especially $proof. That kind of trust deserves a brand presence that makes the same impression before someone calls, clicks, or compares options. I help teams sharpen that identity with branding supported by practical AI tools.`n`nIs this something you've been thinking about?"
    $bodyB = "$greeting`n`nI have worked on brand identity for established names in luxury real estate, where the goal was to make reputation feel clear at first glance. $company has a similar chance: turn existing trust in $city into a more memorable brand system across web, email, and sales touchpoints.`n`nWorth a conversation?"
    if ($category -ne "real estate") {
        $bodyB = "$greeting`n`nI have helped established service brands turn a good reputation into a clearer visual identity, so the first impression matches the quality of the work. $company already has useful proof in $city. A sharper brand system could make that easier for new clients to feel quickly.`n`nWorth a conversation?"
    }
    $bodyC = "$greeting`n`nIn $city, $category brands are competing on trust before people ever make contact. The businesses that stand out usually make their positioning, visuals, and follow-up feel consistent from the first click. $company has the ingredients to make that presence more distinctive and easier to remember.`n`nIs this on your radar?"

    [ordered]@{
        id = Clean-Text $lead.id
        contact_email = Contact-Email $lead
        trigger = $trigger
        outreach_subject = $subjectA
        outreach_draft = $bodyA
        variants = @(
            [ordered]@{ label = "A"; approach = "observation"; subject = $subjectA; body = $bodyA },
            [ordered]@{ label = "B"; approach = "peer"; subject = $subjectB; body = $bodyB },
            [ordered]@{ label = "C"; approach = "opportunity"; subject = $subjectC; body = $bodyC }
        )
        linkedin_profiles = @(Make-LinkedInProfile $lead $greetingName)
    }
}

$leads = Get-Content $toWritePath -Raw | ConvertFrom-Json
$archiveMap = @{}
Get-ChildItem (Join-Path $root "data") -Filter "written_*.json" |
    Sort-Object LastWriteTime -Descending |
    ForEach-Object {
        try {
            $items = Get-Content $_.FullName -Raw | ConvertFrom-Json
            foreach ($item in $items) {
                if ($item.id -and -not $archiveMap.ContainsKey($item.id)) {
                    $archiveMap[$item.id] = $item
                }
            }
        } catch {}
    }

$written = @()
foreach ($lead in $leads) {
    if ($archiveMap.ContainsKey($lead.id)) {
        $entry = $archiveMap[$lead.id]
        $entry.contact_email = Contact-Email $lead
        $written += $entry
    } else {
        $written += Make-Draft $lead
    }
}

$json = $written | ConvertTo-Json -Depth 20
$json = Clean-Text $json
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($outPath, $json, $utf8NoBom)
Write-Output "Wrote $($written.Count) drafts to $outPath"
