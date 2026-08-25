#include <bits/stdc++.h>
using namespace std;
int main() {
    int T;
    cin >> T;
    cin.ignore();
        while(T--){
        string S;
        getline(cin,S);
                stringstream ss(S);
        string word;
        bool first = true ;
                while(ss >> word){
            if(!first) cout<< " ";
            first = false;
                        bool acronym = true;
                        for(char c : word){
                if(!isupper(c)){
                    acronym = false;
                    break;
                }
            }
                        if(acronym){
                cout<<word;
            }
            else{
                word[0] = toupper(word[0]);
                                for(int i = 1; i<word.size(); i++){
                    word[i] = tolower(word[i]);
                }
                cout<<word;
            }
        }
        cout<<'\n';
    }
        return 0;
}
