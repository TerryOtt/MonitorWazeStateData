#!/usr/bin/env python3

# Copyright (c) 2016 Terry D. Ott

import sys

if sys.version_info.major < 3:
    print( "\nERROR: this script must be run with a Python 3.X interpreter." )
    sys.exit()

import argparse
import os
import logging
import re
import urllib.request, urllib.error
import requests
import dateutil.parser
import pytz
import inspect
from pprint import pprint
import subprocess

def main():
    logging.basicConfig(level=logging.INFO)
    args = parseArgs()

    previousDataTimestamp = getPreviousDataTimestamp()
    indexHtmlContent = getHtmlContent(args.rootUrl)

    # Get data timestamp from contents of the index page
    currTimestamp = parseDataTimestampFromIndexPage(indexHtmlContent)

    if _needToDoRun(previousDataTimestamp, currTimestamp) is False:
        sys.exit()

    # Process the content at the index page (link depth = 1)
    processContent(indexHtmlContent, args.rootUrl, 1, args.stateOutputDir, currTimestamp)

    # Write the timestamp to the archive
    writeTimestampToArchive(currTimestamp)


def _needToDoRun(previousDataTimestamp, currTimestamp):
    if previousDataTimestamp is None:
        logging.getLogger(__name__).info('No previous timestamp, doing complete run') 
        return True

    elif currTimestamp <= previousDataTimestamp:
        logging.getLogger(__name__).info('No new data to retrieve ({0} <= {1})'.format(
            currTimestamp, previousDataTimestamp))
        return False

    # If we get here, pull all the data
    logging.getLogger(__name__).info('Previous timestamp of ' +
        prettyPrintTimestamp(previousDataTimestamp) + ' < ' +
        prettyPrintTimestamp(currentTimestamp) +
        ' indicates we need to do complete run!')

    return True 



def parseArgs():
    parser = argparse.ArgumentParser(
        description='Watch state lists for updates, run AM polygons, speed limits, etc. on update')
    parser.add_argument('rootUrl', 
        help='Root of the website where all the good data lives' )
    parser.add_argument('stateOutputDir', 
        help='Root directory where state-specific data, e.g. UR KML and AM polygon KML, should go' )

    args = parser.parse_args()

    validateArgs(args)

    return args


def validateArgs(args):
    
    # Check output directory exists
    if os.path.isdir(args.stateOutputDir) is False:
        logging.getLogger(__name__).error( "Specified state output directory \"" +
            args.stateOutputDir + "\" does not exist")
        sys.exit(-1)


def getPreviousDataTimestamp():
    timestampArchiveDir = os.getcwd() + '/timestamp_archive'
    # If timestamp archive dir doesn't exist, create it
    if os.path.isdir(timestampArchiveDir) is False:
        os.makedirs(timestampArchiveDir)
        logging.getLogger(__name__).info( "Created directory \"" +
            timestampArchiveDir + "\" for timestamps" )

    # Walk through timestamps, if any, and pull most recent
    dataTimestamps = []
    timestampFileExtension = '.timestamp'
    for currFile in os.listdir(timestampArchiveDir):
        supposedTimestamp = currFile[:len(currFile) - len(timestampFileExtension)]
        logging.getLogger(__name__).debug('Found possible timestamp \"' + 
            supposedTimestamp + "\"")
        parsedTimestamp = parseTimestamp(supposedTimestamp)
        if currFile.endswith(timestampFileExtension) is False or \
                parsedTimestamp == None:
            logging.getLogger(__name__).warn( "Found invalid file \"" +
                currFile + "\" in timestamp archive, ignoring" )
            continue

        # Must be valid
        dataTimestamps.append(parsedTimestamp)

    if len(dataTimestamps) > 0:
        return max( dataTimestamps )
    else:
        return None



def parseTimestamp(possibleTimestamp):
    log = logging.getLogger(__name__)

    # Any format that dateutil.parser can parse is good by us, but hoping for ISO8601   
    try: 
        parsedTimestamp = dateutil.parser.parse(possibleTimestamp)
        log.debug("Parsed timestamp \"" + 
            prettyPrintTimestamp(parsedTimestamp) + "\" out of \"" + possibleTimestamp + "\"")

        # force timezone to UTC so everything's comparable
        return pytz.utc.localize(parsedTimestamp)
    except ValueError as e:
        log.error('Could not parse timestamp out of ' + possibleTimestamp)
        raise ValueError('Could not parse timestamp from HTML')
       
    return None


def getHtmlContent(rootUrl):
    log = logging.getLogger(__name__)
    try:
        with urllib.request.urlopen(urllib.request.Request(rootUrl,
                 headers={'User-Agent': 'Mozilla/5.0'})) as urlHandle:


            log.debug('Opened URL ' + rootUrl + ', reading content') 
            htmlContent = urlHandle.read().decode('utf-8')
            log.debug('Successfully read content')

    except urllib.error.HTTPError as e:
        log.error('HTTP error code {0} returned when accessing {1}'.format(
            e.code, rootUrl) )
        sys.exit()
    except urllib.error.URLError as e:
        log.error('Unable to parse URL ' + rootUrl)
        sys.exit()
    except ValueError as e:
        log.error('Unknown URL type ' + rootUrl)
        sys.exit()
    except:
        log.error('Unknown exception when opening ' + rootUrl )
        sys.exit()

    #log.debug("HTML:\n" + htmlContent)

    return htmlContent


def parseDataTimestampFromIndexPage(htmlContent):
    # WARNING: fragile-as-hell parsing, but author didn't give much context to work with
    #
    # Goign for the fact that as of this writing, page has:
    #
    # Generated: 2016-07-20 20:34:36.844030 UTC
    #
    # Going to parse anything beween "Generated:" and "UTC". God help us

    log = logging.getLogger(__name__)

    dateMatch = re.search( 'Generated: (.+?) UTC', htmlContent )

    if dateMatch == None:
        log.error('Could not find possible date string in HTML')
        sys.exit()

    possibleTimestamp = dateMatch.group(1)

    log.debug( "Possible timestamp: " + possibleTimestamp)

    return parseTimestamp(possibleTimestamp)


def prettyPrintTimestamp(timestamp):
    return timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')


def processContent(htmlContent, htmlUrl, linkDepth, stateOutputDir, currTimestamp, recurse=True):
    log = logging.getLogger(__name__)

    (contentScanners, linkScanners) = getContentLinkScanners()

    for currContentScanner in contentScanners:
        currContentScanner(htmlContent, htmlUrl, linkDepth, stateOutputDir, currTimestamp)

    htmlLinks = getHtmlLinks(htmlContent)

    for currHtmlLink in htmlLinks:
        log.debug('Found link ' + currHtmlLink + " in " + htmlUrl )
        for currLinkScanner in linkScanners:
            currLinkScanner( currHtmlLink, htmlUrl, linkDepth, stateOutputDir, currTimestamp)

    # Should we now dive into child links?
    if recurse is True:
        for currHtmlLink in htmlLinks:
            if htmlUrl.endswith('/') is False:
                # If the current URL does NOT end in a slash, need to trim off the last token
                htmlUrl = removeLastToken(htmlUrl)

            parsedHref = parseHref(currHtmlLink)

            newUrl = urllib.parse.urljoin(htmlUrl, urllib.parse.quote(parseHref(currHtmlLink)) )

            if newUrl.endswith('.csv') is True:
                log.debug('Not recursing into link ' + newUrl + ' (CSV file)')
                continue

            log.info("Recursing into " + newUrl)
            newHtmlContent = getHtmlContent(newUrl)
            processContent( newHtmlContent, newUrl, linkDepth + 1, 
                stateOutputDir, currTimestamp, recurse)


# Finds all functions with names that start with "contentScanner_" or "linkScanner_" and
#       returns a tuple with lists of callable objects that match for each

def getContentLinkScanners():
    log = logging.getLogger(__name__)

    contentScanners = []
    linkScanners = []

    for ( globalKey, globalValue ) in globals().items():
        if globalKey.startswith('contentScanner_') is True and callable(globalValue) is True:
            contentScanners.append( globalValue )
            log.debug("Found content scanner: " + globalKey )

        elif globalKey.startswith('linkScanner_') is True and callable(globalValue) is True:
            linkScanners.append( globalValue )
            log.debug( 'Found link scanner: ' + globalKey )

    return (contentScanners, linkScanners)


def linkScanner_getAreaManagerPolygons( linkContent, parentUrl, parentLinkDepth, stateOutputDir,
        currTimestamp ):
    log = logging.getLogger(__name__)

    if re.search('href\s*=\s*"managedareas.csv"', linkContent) != None and \
        parentUrl == 'http://db.slickbox.net/states/' and parentLinkDepth == 1:

        areaManagerPolygonCsv = parentUrl + 'managedareas.csv'

        log.info('Found managed area CSV at ' + areaManagerPolygonCsv + '!' )

    return


def linkScanner_getMissingStateSpeedLimits( linkContent, parentUrl, parentLinkDepth, stateOutputDir,
        currTimestamp ):
    log = logging.getLogger(__name__)

    relativeLink = parseHref(linkContent)
    if relativeLink.endswith('-sl.csv') is False:
        return

    mergedUrl = mergeParentAndRelativeUrl(parentUrl, relativeLink)
    
    log.info( "Found state speed limit CSV at " + mergedUrl )

    # Find out which state we're working with

    # Take last token, trim off known tail of filename
    urlTokens = mergedUrl.split('/')
    stateName = urlTokens[len(urlTokens)-1]
    stateName = stateName[:len(stateName)-len('-sl.csv')]
    
    # Create output directory
    timestampDirName = prettyPrintTimestamp(currTimestamp)

    # Need to do a bit more cleaning to make it a nice directory name
    timestampDirName = timestampDirName.replace( ' ', '_')
    timestampDirName = timestampDirName.replace( '-', '')
    timestampDirName = timestampDirName.replace( ':', '')
    timestampDirName = timestampDirName[:len(timestampDirName)-len('_UTC')]

    outputDir = stateOutputDir + '/' + stateName + '/' + timestampDirName + '/speed_limits'

    if os.path.isdir(outputDir) is False:
        log.info('Creating output directory: ' + outputDir )
        os.makedirs(outputDir)
    else:
        log.warn('Output directory ' + outputDir + ' already existed')

    # Run the KML generator
    executable = 'python3'
    script = '/home/tdo/projects/segmentcsv2kml/segmentcsv2kml.py'
    subprocess.call( ["python3", script, mergedUrl, outputDir] )


def getHtmlLinks(htmlContent):
    log = logging.getLogger(__name__)

    returnLinks = []

    # Only return relative links (remove any with http:// at the beginning)
    for potentialLink in re.findall( '<a\s+href.*?<\/a>', htmlContent ):
        hrefPortion = parseHref(potentialLink)
        if hrefPortion.startswith('http://') is False and \
                hrefPortion.startswith('https://') is False:
            returnLinks.append(potentialLink)
            log.debug("Added " + potentialLink + " as it's relative" )

    return returnLinks


def parseHref(htmlLink):
    log = logging.getLogger(__name__)

    patternMatches = re.search('href\s*=\s*"(.+?)"', htmlLink)

    if patternMatches == None:
        log.error('Could not parse Href value out of ' + htmlLink)
        sys.exit()

    return patternMatches.group(1)


def removeLastToken(url):
    log = logging.getLogger(__name__)
    # log.debug("Removing last token from " + url)

    # delete to last slash
    for i in range(len(url) - 1, 0, -1):
        if url[i] == '/':
            trimmedUrl = url[:i + 1]
            # log.debug( 'Trimmed URL: ' + trimmedUrl)
            return trimmedUrl

    log.error('Should never get here')
    sys.exit()

def mergeParentAndRelativeUrl( parentUrl, relativeUrl ):

    if parentUrl.endswith('/'):
        return parentUrl + relativeUrl
    else:
        return removeLastToken(parentUrl) + relativeUrl


def touch(fname, times=None):
    with open(fname, 'a'):
        os.utime(fname, times)


def writeTimestampToArchive(currTimestamp):
    timestampArchiveDir = os.getcwd() + '/timestamp_archive' 

    touch(os.path.join(timestampArchiveDir, currTimestamp.strftime('%Y-%m-%d %H:%M:%S.timestamp')))


    
    

if __name__ == '__main__':
    main()
