import os, winsound, sys, requests, sqlite3, json
from distutils import dir_util
from mutagen.flac import FLAC
import eyed3
from colorama import Fore, init
init(autoreset=True)


argList = sys.argv
validArgs = ['--no-retransfers', '--skip-various']
for arg in argList[1:]:
    if arg not in validArgs:
        raise Exception('error: invalid argument passed')

CONFIGFILEPATH = ''

consts = json.load(open(CONFIGFILEPATH, 'r'))
STARTPATH = consts['COMPLETED_DLS_DIR']
DESTPATH = consts['SERVER_MUSIC_DIR']
PLEXTOKEN = consts['PLEX_AUTH_TOKEN']
PLEXSERVERPORT = consts["PLEX_SERVER_PORT"]
PLEXSERVERIP = consts["PLEX_SERVER_IP"]
PLEXMUSICLIBNUM = consts["PLEX_MUSIC_LIB_NUM"]
ARTISTCHARFILTER = consts["CHAR_FILTER"]
DBFILE = consts["DATABASE_FILE"]
EXTENSIONS = ['.flac', '.mp3']
PLEXREQUEST = ''.join(['http://', PLEXSERVERIP, ':', str(PLEXSERVERPORT), '/library/sections/', str(PLEXMUSICLIBNUM), '/refresh?X-Plex-Token=', PLEXTOKEN])
SKIPBYPASS = False
RETRANSFERBYPASS = False
SILENTMODE = False
DBCONNECT = sqlite3.connect(DBFILE)


query = DBCONNECT.cursor()
movedTable = query.execute('SELECT * FROM REDtorrents;').fetchall()
movedThisSession = []

trueTransfers = 0


#FUNCTION DEFS
def currentDirMsg(directory):
    print(' '.join(['Rel:', directory, ]))


#message to print when copying to dir
def copyingToDirMsg(directory):
    print(' '.join(['\t', 'copying files to', directory]))


#message to print when creating new directory
def creatingDirMsg(directory):
    print(' '.join(['\t', 'making new directory', directory]))


def collectFileArtists(filePath):
    if os.path.splitext(filePath)[1] in ['.flac', '.FLAC']:
        return [x for x in FLAC(filePath)["ARTIST"]]
    elif os.path.splitext(filePath)[1] in ['.mp3', '.MP3']:
        return [eyed3.load(filePath).tag.artist]


#given a full directory path to release folder and parses each unique artist from each audio file
def collectArtistsFrom(releaseDir):
    artists = []
    releaseDirList = os.listdir(releaseDir)
    try:
        for i in range(len(releaseDirList)):
            #current item is within release dir
            releaseDirItem = os.path.join(releaseDir, releaseDirList[i])
            #only continue if file
            if os.path.isfile(releaseDirItem):
                # only continue if file is FLAC
                if os.path.splitext(releaseDirItem)[1] in EXTENSIONS:
                    for entry in collectFileArtists(releaseDirItem):
                        if entry not in artists:
                            artists.append(entry)

        #special case in which a release is a multifolder release, eg double LP, CD and no music is present in the main directory of the release
        if len(artists) == 0:
            for i in range(len(releaseDirList)):
                releaseDirItem = os.path.join(releaseDir, releaseDirList[i])
                # if the item in the release directory is a directory:
                if os.path.isdir(releaseDirItem):
                    releaseSubdirList = os.listdir(releaseDirItem)
                    #while counter is going through each separate disk 
                    for x in range(len(releaseSubdirList)):
                        #current item is within subdir
                        releaseSubdirItem = os.path.join(releaseDirItem, releaseSubdirList[x])
                        #only continue if file
                        if os.path.isfile(releaseSubdirItem):
                            # only continue if file is FLAC or MP3
                            if os.path.splitext(releaseSubdirItem)[1] in EXTENSIONS:
                                for entry in collectFileArtists(releaseSubdirItem):
                                    if entry not in artists:
                                        artists.append(entry)
    except KeyError:
        return []
    return artists


#takes a list of artists and replaces any forbidden characters with an underscore to prevent syntax/system errors w/ naming
def forbiddenCharScrub(artistList):
    #for every artist in the list
    for a in range(len(artistList)):
        #for every character in each artist name
        for b in range(len(artistList[a])):
            #i call this the "Fred Again.." scrub to avoid linux complications with double periods
            if b + 1 < len(artistList[a]):
                if artistList[a][b] + artistList[a][b + 1] == '..':
                    tempList = list(artistList[a])
                    tempList[b] = '_'
                    tempList[b + 1] = '_'
                    artistList[a] = ''.join(tempList)
            #if that character is in the filter
            if artistList[a][b] in ARTISTCHARFILTER:
                #replace with an underscore
                winsound.MessageBeep()
                print(Fore.YELLOW + "Artist name " + artistList[a] + " contains contains at least one forbidden filename character. Replacing with underscore '_' char")
                tempList = list(artistList[a])
                tempList[b] = '_'
                artistList[a] = ''.join(tempList)
    return artistList


#appends the release to the list of releases moved this current session
def setToTransferred(transferredPath, releaseName):
    query.execute('UPDATE REDtorrents SET transferredPath = "' + transferredPath + '" WHERE folderName = "' + releaseName + '"')
    DBCONNECT.commit()
    print('\ttransfer path added to torrent database')


#copies the given dirpath to the given dest path
def copyReleaseDir(fullReleasePath, fullDestPath):
    global trueTransfers
    folderName = os.path.basename(os.path.normpath(fullReleasePath))
    dir_util.copy_tree(fullReleasePath, fullDestPath)
    setToTransferred(fullDestPath, folderName)
    trueTransfers += 1


#like collectArtistsFrom but just counts the total number of times an artist appears in the files and returns the most frequent one
def mostCommonArtist(releaseDir):
    artists = {}
    releaseDirList = os.listdir(releaseDir)
    for i in range(len(releaseDirList)):
        #current item is within release dir
        releaseDirItem = os.path.join(releaseDir, releaseDirList[i])
        #only continue if file
        if os.path.isfile(releaseDirItem):
            # only continue if file is FLAC
            if os.path.splitext(releaseDirItem)[1] in EXTENSIONS:
                for entry in collectFileArtists(releaseDirItem):
                    if entry not in artists.keys():
                        artists[str(entry)] = 0
                    artists[str(entry)] += 1
    #special case in which a release is a multifolder release, eg double LP, CD and no music is present in the main directory of the release
    if len(artists) == 0:
        for i in range(len(releaseDirList)):
            releaseDirItem = os.path.join(releaseDir, releaseDirList[i])
            # if the item in the release directory is a directory:
            if os.path.isdir(releaseDirItem):
                releaseSubdirList = os.listdir(releaseDirItem)
                #while counter is going through each separate disk 
                for x in range(len(releaseSubdirList)):
                    #current item is within subdir
                    releaseSubdirItem = os.path.join(releaseDirItem, releaseSubdirList[x])
                    #only continue if file
                    if os.path.isfile(releaseSubdirItem):
                        # only continue if file is FLAC
                        if os.path.splitext(releaseSubdirItem)[1] in EXTENSIONS:
                            for entry in collectFileArtists(releaseSubdirItem):
                                if entry not in artists.keys():
                                    artists[str(entry)] = 0
                                artists[str(entry)] += 1
    return max(artists)


def soundPlay():
    if SILENTMODE:
        pass
    else:
        winsound.MessageBeep()


def returnExistingName(artistName):
    #ignoring case, check if artist name is in music directory 
    artistsList = [x for x in os.listdir(DESTPATH)]
    for existingArtist in artistsList:

        #if so, return name of artist as it already exists in dir
        if artistName.casefold() == existingArtist.casefold() and artistName != existingArtist:
            print('\tthe artist folder for', artistName, 'already exists in server as', existingArtist, ', adjusting destination dir')
            return existingArtist

    #if not, return original name
    return artistName



#MAIN PROGRAM
#for every subdir and file in starting directory
sourceDirList = os.listdir(STARTPATH)

justFolderNames = [i[6] for i in movedTable]

for sourceDirItem in sourceDirList:
    #if the dir item is a folder, already has an entry in the DB from REDtop10, and doesnt have a transferred directory set
    if os.path.isdir(os.path.join(STARTPATH, sourceDirItem)) and (sourceDirItem in justFolderNames) and (movedTable[justFolderNames.index(sourceDirItem)][7] == None):
        #using release now that we know its a folder not any potential kind of item
        #retrieving artists from files
        release = sourceDirItem
        releasePath = os.path.join(STARTPATH, release)
        currentDirMsg(release)            
        artists = collectArtistsFrom(releasePath)
        artists = forbiddenCharScrub(artists)
        if len(artists) == 0:
            soundPlay()
            print(Fore.RED + '\tNo artists pulled from folder.')
            if '--skip-various' in sys.argv or SKIPBYPASS:
                continue
            else:
                artistFolder = input('\tEnter an artist name to put this release into: ')
                destArtistPath = os.path.join(DESTPATH, artistFolder)
                destReleasePath = os.path.join(destArtistPath, release)

        #if only one unique artist tag found in all music files, make directory with artist name in dest directory and copy release folder over
        if len(artists) == 1:
            confirmedArtist = returnExistingName(artists[0].strip())
            destArtistPath = os.path.join(DESTPATH,confirmedArtist)
            destReleasePath = os.path.join(destArtistPath, release)

        elif len(artists) > 1:
            if '--skip-various' in sys.argv or SKIPBYPASS:
                print('\trelease contains multiple artists, skipping for now\n')
                continue
            else:
                soundPlay()
                mostCommon = mostCommonArtist(releasePath)
                manualArtist = input(''.join(['\t', 'Release "', release, '" has differing artist tags across its audio files.', '\n\t', 'Enter artist folder name, press ENTER for "Various Artists", or type "top" for ' + mostCommon + ': ']))
                if manualArtist == '':
                    destArtistPath = os.path.join(DESTPATH, "Various Artists")
                elif manualArtist.lower() == 'top':
                    destArtistPath = os.path.join(DESTPATH, mostCommon)
                else:
                    destArtistPath = os.path.join(DESTPATH, manualArtist)

                destReleasePath = os.path.join(destArtistPath, release)




        if not os.path.exists(destArtistPath):
            creatingDirMsg(destArtistPath)
            os.mkdir(destArtistPath)

        #COPYING SEGMENT
        #if the release folder already exists in the destination dir ask for retransfer or just append to list (for partial transfers or other side occurrences)
        if os.path.exists(os.path.join(destArtistPath, release)):
            soundPlay()
            if '--no-retransfer' in sys.argv or RETRANSFERBYPASS:
                print(Fore.YELLOW + '\tRelease folder already present in destination directory, adding path to torrent database')
                query.execute('UPDATE REDtorrents SET transferredPath = "' + os.path.join(destArtistPath, release) + '" WHERE folderName = "' + release + '"')

            else:
                print('\tRelease folder already present in destination directory, retransferring files')
                copyingToDirMsg(destArtistPath)
                copyReleaseDir(releasePath, destReleasePath)

        else:
            copyingToDirMsg(destArtistPath)
            copyReleaseDir(releasePath, destReleasePath)

        
        print('\n')

#below may be disabled because plex takes too long scanning library now, hangs on various old releases, idk why. plex wont autodetect despite settings being set

if trueTransfers > 0:
    print('sending scan request to Plex server')
    requests.get(PLEXREQUEST)
